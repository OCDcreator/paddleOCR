from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any

import pypdfium2
import uvicorn
from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from starlette.concurrency import run_in_threadpool

from paddleocr_service.config import Settings, get_settings
from paddleocr_service.database import JobRepository
from paddleocr_service.engines.registry import available_engines, create_engine
from paddleocr_service.jobs import (
    OCRJobQueue,
    build_handler_from_source,
    process_image_batch_job,
    process_pdf_job,
    source_payload_for_images,
    source_payload_for_pdf,
)
from paddleocr_service.operations import AccessLogMiddleware, cleanup_expired_jobs
from paddleocr_service.pdf import render_pdf_pages
from paddleocr_service.schemas import HealthResponse, OCRResponse
from paddleocr_service.storage import LocalStorage, OutputFormat


def create_app(
    ocr_engine: Any | None = None,
    settings: Settings | None = None,
    job_queue: OCRJobQueue | None = None,
    pdf_renderer: Any | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    engine = ocr_engine or create_engine(app_settings.engine, app_settings)
    warmup = WarmupCoordinator()
    # Last engine confirmed ready (name, instance), used as an auto-fallback
    # target if a swap's warmup fails. Only set when the current engine is ready,
    # so we never roll back to an unverified engine.
    known_good_engine: tuple[str, Any] | None = None
    if engine.is_ready:
        known_good_engine = (app_settings.engine, engine)
    # Bumped on every swap; a background fallback checks it before committing, so
    # a newer user-initiated swap is never overwritten by a stale rollback.
    engine_generation = 0
    storage = LocalStorage(app_settings)
    storage.ensure_base_dirs()
    repository = JobRepository(app_settings.database_path)
    strict_pdf_validation = pdf_renderer is None

    def render_pdf(pdf_bytes: bytes) -> list[bytes]:
        if pdf_renderer is not None:
            return pdf_renderer(pdf_bytes)
        return render_pdf_pages(pdf_bytes, scale=app_settings.pdf_render_scale)

    queue = job_queue or OCRJobQueue(repository=repository, storage=storage)
    static_dir = Path(__file__).parent / "static"

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await queue.start()
        if app_settings.warmup_on_startup and hasattr(engine, "warm_up"):
            engine.warm_up()
        try:
            yield
        finally:
            await queue.stop()

    app = FastAPI(
        title="PaddleOCR LAN Service",
        version="0.1.0",
        description="Expose local PaddleOCR as a LAN HTTP API.",
        lifespan=lifespan,
    )
    app.add_middleware(AccessLogMiddleware, settings=app_settings)
    if app_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    def _fallback_on_failure() -> None:
        """Auto-rollback to the last known-good engine when a warmup fails.

        Called from the WarmupCoordinator when the current engine's background
        warmup raised. Guards against: (a) no known-good target (nothing to roll
        back to — e.g. startup, or the prior engine was never verified), (b) a
        newer user swap superseding this one (generation check — never clobber a
        fresh user intent), and (c) infinite loops (only rolls back to a target
        that was confirmed ready at swap time, so its warmup is very unlikely to
        fail; if it does, we stop — phase stays 'failed').
        """
        nonlocal engine, app_settings, engine_generation
        if known_good_engine is None:
            return
        # If a newer swap happened since this warmup started, do NOT roll back —
        # the user's latest intent wins.
        if engine_generation != warmup.fallback_generation:
            return
        name, good_engine = known_good_engine
        app_settings.engine = name
        engine = good_engine
        engine_generation += 1
        warmup.public_reset_idle()

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/health", response_model=HealthResponse)
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "engine_ready": bool(engine.is_ready),
            "engine": app_settings.engine,
            "queue": queue.stats(),
            "version": _package_version(),
            "warmup": warmup.public_state(),
            "settings": _public_settings(app_settings, engine),
            "storage": {
                "database_path": str(app_settings.database_path),
                "output_dir": str(app_settings.output_dir),
                "upload_dir": str(app_settings.upload_dir),
                "output_bytes": storage.output_bytes(),
                "upload_bytes": storage.upload_bytes(),
            },
            "model_cache_path": str(Path.home() / ".paddlex" / "official_models"),
        }

    @app.post("/ocr", response_model=OCRResponse)
    async def ocr(
        image: Annotated[UploadFile, File(...)],
        content_length: Annotated[int | None, Header()] = None,
    ) -> dict[str, Any]:
        if image.content_type is None or not image.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Uploaded file must be an image.")

        _enforce_request_size_limit(content_length, app_settings.max_upload_bytes)
        image_bytes = await image.read()
        _enforce_upload_limit([image_bytes], app_settings.max_upload_bytes)
        start = time.perf_counter()
        try:
            items = await run_in_threadpool(partial(engine.recognize, image_bytes))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return {
            "text": "\n".join(item["text"] for item in items),
            "items": items,
            "elapsed_ms": elapsed_ms,
        }

    @app.post("/jobs/images", status_code=202)
    async def submit_image_batch(
        images: Annotated[list[UploadFile], File(...)],
        content_length: Annotated[int | None, Header()] = None,
    ) -> dict[str, Any]:
        if not images:
            raise HTTPException(status_code=400, detail="At least one image is required.")
        _enforce_request_size_limit(content_length, app_settings.max_upload_bytes)

        image_payloads: list[tuple[str, bytes]] = []
        for image in images:
            if image.content_type is None or not image.content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="All uploaded files must be images.")
            payload = await image.read()
            _validate_image_bytes(payload)
            image_payloads.append((image.filename or "image", payload))
        _enforce_upload_limit(
            [payload for _, payload in image_payloads],
            app_settings.max_upload_bytes,
        )

        source_payload = (
            source_payload_for_images(image_payloads) if app_settings.save_uploads else None
        )
        job = await queue.submit(
            kind="image_batch",
            total_units=len(image_payloads),
            handler=partial(process_image_batch_job, engine=engine, images=image_payloads),
            source_payload=source_payload,
        )
        for filename, payload in image_payloads:
            storage.save_upload(job.id, filename, payload)
        return job.to_dict()

    @app.post("/jobs/pdf", status_code=202)
    async def submit_pdf(
        pdf: Annotated[UploadFile, File(...)],
        content_length: Annotated[int | None, Header()] = None,
    ) -> dict[str, Any]:
        if pdf.content_type != "application/pdf":
            raise HTTPException(status_code=400, detail="Uploaded file must be a PDF.")

        _enforce_request_size_limit(content_length, app_settings.max_upload_bytes)
        pdf_bytes = await pdf.read()
        _enforce_upload_limit([pdf_bytes], app_settings.max_upload_bytes)
        _validate_pdf_bytes(pdf_bytes, strict=strict_pdf_validation)
        filename = pdf.filename or "document.pdf"
        source_payload = (
            source_payload_for_pdf(filename, pdf_bytes) if app_settings.save_uploads else None
        )
        job = await queue.submit(
            kind="pdf",
            total_units=1,
            handler=partial(
                process_pdf_job,
                engine=engine,
                filename=filename,
                pdf_bytes=pdf_bytes,
                pdf_renderer=render_pdf,
            ),
            source_payload=source_payload,
        )
        storage.save_upload(job.id, filename, pdf_bytes)
        return job.to_dict()

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        job = queue.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        return job.to_dict()

    @app.get("/jobs")
    def list_jobs() -> dict[str, Any]:
        return {"jobs": [job.to_dict() for job in queue.recent()]}

    @app.get("/jobs/{job_id}/download/{output_format}")
    def download_job_output(job_id: str, output_format: OutputFormat) -> FileResponse:
        job = queue.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        path = storage.output_path(job_id, output_format)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Output file not found.")
        media_type = {
            "json": "application/json",
            "txt": "text/plain; charset=utf-8",
            "markdown": "text/markdown; charset=utf-8",
        }[output_format]
        return FileResponse(path, media_type=media_type, filename=path.name)

    @app.post("/jobs/{job_id}/retry", status_code=202)
    async def retry_job(job_id: str) -> dict[str, Any]:
        job = queue.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found.")
        handler = build_handler_from_source(job.source_payload, engine, render_pdf)
        retried = await queue.retry(job_id, handler)
        if retried is None:
            raise HTTPException(status_code=409, detail="Job cannot be retried.")
        return retried.to_dict()

    @app.post("/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, Any]:
        job = queue.cancel(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Cancelable job not found.")
        return job.to_dict()

    @app.delete("/jobs/{job_id}")
    def delete_job(job_id: str) -> dict[str, Any]:
        deleted = queue.delete(job_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Job not found.")
        return {"deleted": True, "id": job_id}

    @app.post("/queue/pause")
    def pause_queue() -> dict[str, Any]:
        queue.pause()
        return {"queue": queue.stats()}

    @app.post("/queue/resume")
    def resume_queue() -> dict[str, Any]:
        queue.resume()
        return {"queue": queue.stats()}

    @app.get("/settings")
    def get_runtime_settings() -> dict[str, Any]:
        return _public_settings(app_settings, engine)

    @app.get("/engines")
    def list_engines() -> dict[str, Any]:
        """Return the available engine names and the currently-selected one.

        Used by the frontend to populate the engine selector dynamically, so a
        newly registered engine appears without a frontend edit.
        """
        return {"engines": available_engines(), "current": app_settings.engine}

    @app.patch("/settings")
    async def update_runtime_settings(payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal engine, known_good_engine, engine_generation
        _validate_settings_patch(payload)

        # 1. Swap engine first if requested.
        swapped = False
        if "engine" in payload and payload["engine"] != app_settings.engine:
            new_name = payload["engine"]
            if new_name not in available_engines():
                raise HTTPException(
                    status_code=422,
                    detail=f"unknown engine: {new_name!r} (available: {available_engines()})",
                )
            new_engine = create_engine(new_name, app_settings)
            # Fail fast if the engine's library is not installed: verify the import
            # before committing the swap, so a missing library returns 422 instead of
            # silently replacing the engine with one that breaks the next recognize().
            try:
                new_engine.verify_available()
            except ImportError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"engine {new_name!r} is not available: {exc}. "
                        f"Install its package (e.g. `uv sync --extra {new_name}`)."
                    ),
                ) from exc
            # Record the current engine as a fallback target ONLY if it is ready,
            # so a failed warmup can roll back to a known-good engine (never to an
            # unverified one). Captured before the swap so it reflects pre-swap state.
            this_generation = engine_generation + 1
            if engine.is_ready:
                known_good_engine = (app_settings.engine, engine)
            app_settings.engine = new_name
            engine = new_engine
            engine_generation = this_generation
            swapped = True

        # 2. Apply remaining keys to the (possibly new) current engine.
        engine_keys = {s.key for s in engine.supported_settings()}
        app_level_keys = {
            "warmup_on_startup",
            "save_uploads",
            "max_upload_bytes",
            "pdf_render_scale",
            "retention_days",
        }
        unknown = set(payload) - {"engine"} - engine_keys - app_level_keys
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"engine {engine.name!r} does not support key(s): {sorted(unknown)}",
            )

        for key, value in payload.items():
            # Persist onto app_settings when the field exists there (covers both
            # app-level keys and engine keys that also live on Settings, e.g.
            # language/use_angle_cls for PaddleOCR).
            if key in app_level_keys or hasattr(app_settings, key):
                setattr(app_settings, key, value)
        # Push every engine-level key that the engine supports AND that exists on
        # app_settings, using the current app_settings value. This mirrors the old
        # configure(language, use_angle_cls) behavior: the engine always reflects
        # the current settings, not just the keys in this PATCH body.
        engine_opts = {
            k: getattr(app_settings, k) for k in engine_keys if hasattr(app_settings, k)
        }
        if engine_opts:
            try:
                engine.apply_settings(**engine_opts)
            except Exception as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        storage.ensure_base_dirs()
        # After a swap, warm the new engine in the background so the PATCH returns
        # immediately (a cold warm_up takes 12-27s). The task is guarded by the
        # engine generation: if another swap supersedes this one before the warmup
        # finishes, the warmup aborts instead of touching the newer engine.
        if swapped:
            # Every swap cancels the prior in-flight warmup. A new warmup is
            # started only if the newly installed engine is not already ready.
            if engine.is_ready:
                warmup.cancel()
            else:
                warmup.start(
                    engine,
                    app_settings.engine,
                    on_failure=_fallback_on_failure,
                    generation=engine_generation,
                )
        return _public_settings(app_settings, engine)

    @app.post("/operations/warmup")
    async def warmup_model() -> dict[str, Any]:
        if not hasattr(engine, "warm_up"):
            raise HTTPException(status_code=409, detail="OCR engine does not support warmup.")
        # Manual warmup is synchronous by contract (the caller explicitly asked to
        # load the model and waits for it). Swap-triggered warmup, by contrast, is
        # background via WarmupCoordinator. Mark the coordinator idle so /health
        # does not report a stale "warming" phase from a prior cancelled swap.
        warmup.cancel()
        await run_in_threadpool(engine.warm_up)
        return {"engine_ready": bool(engine.is_ready), "engine": app_settings.engine}

    @app.post("/operations/retention/cleanup")
    def cleanup_retention() -> dict[str, Any]:
        result = cleanup_expired_jobs(
            settings=app_settings,
            repository=repository,
            storage=storage,
        )
        for job_id in result.get("job_ids", []):
            queue.forget(job_id)
        return {key: value for key, value in result.items() if key != "job_ids"}

    return app


class WarmupCoordinator:
    """Tracks the single current background warmup: phase + cancelable task.

    phase ∈ {"idle", "warming", "failed"}. A successful warmup surfaces as
    engine.is_ready True (phase returns to "idle"); a failed one sets phase
    "failed" with an error message. At most one warmup is tracked at a time:
    calling start() again cancels any in-flight task (soft cancel — the
    underlying library call in the threadpool keeps running to completion, but we
    stop awaiting it and discard its result).
    """

    def __init__(self) -> None:
        self.phase: str = "idle"
        self.started_at: str | None = None
        self.engine_name: str | None = None
        self.error: str | None = None
        self._task: asyncio.Task[None] | None = None
        # Generation captured when a warmup starts, so an auto-fallback handler
        # can tell whether it still owns the current engine or a newer swap
        # superseded it. Public so the create_app fallback closure can read it.
        self.fallback_generation: int = 0

    def start(
        self,
        engine: Any,
        engine_name: str,
        on_failure: Any = None,
        generation: int = 0,
    ) -> None:
        self.cancel()
        self.phase = "warming"
        self.started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.engine_name = engine_name
        self.error = None
        self.fallback_generation = generation

        async def _warmup() -> None:
            failed = False
            try:
                await run_in_threadpool(engine.warm_up)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                self.phase = "failed"
                self.error = f"{type(exc).__name__}: {exc}"
                failed = True
            if failed:
                # Hand control to the fallback handler if one was provided. It may
                # roll back the live engine and reset phase to idle; if it does
                # nothing, phase stays "failed".
                if on_failure is not None:
                    on_failure()
                return
            # If we were cancelled mid-flight, a sibling cancel() already reset
            # state; only mark success if we are still the tracked task.
            if self._task is not None and asyncio.current_task() is self._task:
                self.phase = "idle"
                self.error = None

        self._task = asyncio.create_task(_warmup())

    def cancel(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self._task = None
        self.phase = "idle"
        self.started_at = None
        self.error = None

    def public_reset_idle(self) -> None:
        """Reset phase/started_at/error to idle (used after a successful rollback)."""
        self.phase = "idle"
        self.started_at = None
        self.error = None

    def public_state(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "started_at": self.started_at,
            "engine": self.engine_name,
            "error": self.error,
        }


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "paddleocr_service.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()


def _public_settings(settings: Settings, engine: Any | None = None) -> dict[str, Any]:
    result = {
        "engine": settings.engine,
        "language": settings.language,
        "use_angle_cls": settings.use_angle_cls,
        "warmup_on_startup": settings.warmup_on_startup,
        "save_uploads": settings.save_uploads,
        "max_upload_bytes": settings.max_upload_bytes,
        "pdf_render_scale": settings.pdf_render_scale,
        "retention_days": settings.retention_days,
        "cors_origins": settings.cors_origins,
        "access_log_path": str(settings.access_log_path),
    }
    if engine is not None:
        result["supported_settings"] = [
            {"key": s.key, "type": s.type, "description": s.description}
            for s in engine.supported_settings()
        ]
    return result


def _enforce_upload_limit(payloads: list[bytes], max_upload_bytes: int) -> None:
    if sum(len(payload) for payload in payloads) > max_upload_bytes:
        raise HTTPException(status_code=413, detail="Upload exceeds configured size limit.")


def _enforce_request_size_limit(content_length: int | None, max_upload_bytes: int) -> None:
    if content_length is not None and content_length > max_upload_bytes:
        raise HTTPException(status_code=413, detail="Upload exceeds configured size limit.")


def _validate_image_bytes(payload: bytes) -> None:
    try:
        with Image.open(BytesIO(payload)) as image:
            image.verify()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Uploaded file must be an image.") from exc


def _validate_pdf_bytes(payload: bytes, *, strict: bool) -> None:
    if not payload.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Uploaded file must be a valid PDF.")
    if not strict:
        return
    try:
        document = pypdfium2.PdfDocument(payload)
        len(document)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Uploaded file must be a valid PDF.") from exc


def _package_version() -> str:
    try:
        return version("paddleocr-lan-service")
    except PackageNotFoundError:
        return "0.1.0"


def _validate_settings_patch(payload: dict[str, Any]) -> None:
    validators = {
        "language": _validate_non_empty_string,
        "max_upload_bytes": _validate_positive_int,
        "pdf_render_scale": _validate_pdf_render_scale,
        "retention_days": _validate_non_negative_int,
    }
    for key, validator in validators.items():
        if key in payload:
            validator(key, payload[key])


def _validate_non_empty_string(key: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=422, detail=f"{key} must be a non-empty string.")


def _validate_positive_int(key: str, value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise HTTPException(status_code=422, detail=f"{key} must be a positive integer.")


def _validate_non_negative_int(key: str, value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise HTTPException(status_code=422, detail=f"{key} must be a non-negative integer.")


def _validate_pdf_render_scale(key: str, value: Any) -> None:
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0:
        raise HTTPException(status_code=422, detail=f"{key} must be greater than 0.")
