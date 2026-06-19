from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from starlette.concurrency import run_in_threadpool

from paddleocr_service.database import JobRepository
from paddleocr_service.storage import LocalStorage

OCRItemDict = dict[str, Any]
JobKind = Literal["image_batch", "pdf"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "canceled"]
SourcePayload = dict[str, Any]


@dataclass
class OCRPageResult:
    page_number: int
    text: str
    items: list[OCRItemDict]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "page_number": self.page_number,
            "text": self.text,
            "items": self.items,
        }
        if self.error is not None:
            data["error"] = self.error
        return data


@dataclass
class OCRDocumentResult:
    filename: str
    pages: list[OCRPageResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "filename": self.filename,
            "pages": [page.to_dict() for page in self.pages],
        }


@dataclass
class OCRJob:
    id: str
    kind: JobKind
    status: JobStatus
    total_units: int
    completed_units: int = 0
    documents: list[OCRDocumentResult] = field(default_factory=list)
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    source_payload: SourcePayload | None = None
    output_paths: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    canceled: bool = False
    attempt: int = 0

    @classmethod
    def from_record(cls, record: dict[str, Any], storage: LocalStorage) -> OCRJob:
        job = cls(
            id=record["id"],
            kind=record["kind"],
            status=record["status"],
            total_units=record["total_units"],
            completed_units=record["completed_units"],
            error=record["error"],
            created_at=record["created_at"],
            started_at=record["started_at"],
            finished_at=record["finished_at"],
            source_payload=record.get("source_payload"),
            output_paths=record.get("output_paths", {}),
            canceled=record.get("canceled", False),
        )
        job.documents = [
            OCRDocumentResult(
                filename=document["filename"],
                pages=[
                    OCRPageResult(
                        page_number=page["page_number"],
                        text=page.get("text", ""),
                        items=page.get("items", []),
                        error=page.get("error"),
                    )
                    for page in document.get("pages", [])
                ],
            )
            for document in record.get("documents", [])
        ]
        job.outputs = storage.output_urls(job.id)
        return job

    def reset_for_retry(self) -> None:
        self.status = "queued"
        self.completed_units = 0
        self.documents = []
        self.error = None
        self.started_at = None
        self.finished_at = None
        self.output_paths = {}
        self.outputs = {}
        self.canceled = False
        self.attempt += 1

    def to_dict(
        self,
        *,
        include_source_payload: bool = False,
        include_output_paths: bool = False,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "total_units": self.total_units,
            "completed_units": self.completed_units,
            "documents": [document.to_dict() for document in self.documents],
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "outputs": self.outputs,
        }
        if include_source_payload:
            data["source_payload"] = self.source_payload
            data["canceled"] = self.canceled
        if include_output_paths:
            data["output_paths"] = self.output_paths
        return data


JobHandler = Callable[[OCRJob], Any]


class OCRJobQueue:
    def __init__(
        self,
        repository: JobRepository,
        storage: LocalStorage,
        max_recent_jobs: int = 100,
    ) -> None:
        self._queue: asyncio.Queue[tuple[str, JobHandler, int]] = asyncio.Queue()
        self._jobs: dict[str, OCRJob] = {}
        self._handlers: dict[str, JobHandler] = {}
        self._repository = repository
        self._storage = storage
        self._max_recent_jobs = max_recent_jobs
        self._worker_task: asyncio.Task[None] | None = None
        self._paused = False
        self._resume_event = asyncio.Event()
        self._resume_event.set()
        self._load_persisted_jobs()

    @property
    def is_running(self) -> bool:
        return self._worker_task is not None and not self._worker_task.done()

    @property
    def paused(self) -> bool:
        return self._paused

    async def start(self) -> None:
        if not self.is_running:
            self._worker_task = asyncio.create_task(self._work())

    async def stop(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    async def submit(
        self,
        kind: JobKind,
        total_units: int,
        handler: JobHandler,
        source_payload: SourcePayload | None = None,
    ) -> OCRJob:
        await self.start()
        job = OCRJob(
            id=uuid.uuid4().hex,
            kind=kind,
            status="queued",
            total_units=total_units,
            source_payload=source_payload,
        )
        self._jobs[job.id] = job
        self._handlers[job.id] = handler
        self._persist(job)
        await self._queue.put((job.id, handler, job.attempt))
        return job

    async def retry(self, job_id: str, handler: JobHandler | None = None) -> OCRJob | None:
        job = self.get(job_id)
        if job is None or job.status not in {"failed", "canceled"}:
            return None
        handler = handler or self._handler_from_source(job)
        if handler is None:
            return None
        self._storage.delete_job_files(job.id)
        job.reset_for_retry()
        self._handlers[job.id] = handler
        self._persist(job)
        await self._queue.put((job.id, handler, job.attempt))
        await self.start()
        return job

    def cancel(self, job_id: str) -> OCRJob | None:
        job = self.get(job_id)
        if job is None or job.status not in {"queued", "running"}:
            return None
        job.canceled = True
        job.status = "canceled"
        job.error = "Canceled by user."
        job.finished_at = time.time()
        self._persist(job)
        return job

    def delete(self, job_id: str) -> bool:
        self._jobs.pop(job_id, None)
        self._handlers.pop(job_id, None)
        deleted = self._repository.delete(job_id)
        self._storage.delete_job_files(job_id)
        return deleted

    def forget(self, job_id: str) -> None:
        self._jobs.pop(job_id, None)
        self._handlers.pop(job_id, None)

    def pause(self) -> None:
        self._paused = True
        self._resume_event.clear()

    def resume(self) -> None:
        self._paused = False
        self._resume_event.set()

    def get(self, job_id: str) -> OCRJob | None:
        job = self._jobs.get(job_id)
        if job is not None:
            job.outputs = self._storage.output_urls(job.id)
        return job

    def recent(self) -> list[OCRJob]:
        jobs = sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)
        for job in jobs:
            job.outputs = self._storage.output_urls(job.id)
        return jobs[: self._max_recent_jobs]

    def stats(self) -> dict[str, int | bool]:
        running = sum(1 for job in self._jobs.values() if job.status == "running")
        queued = sum(1 for job in self._jobs.values() if job.status == "queued")
        succeeded = sum(1 for job in self._jobs.values() if job.status == "succeeded")
        failed = sum(1 for job in self._jobs.values() if job.status == "failed")
        canceled = sum(1 for job in self._jobs.values() if job.status == "canceled")
        return {
            "running": running,
            "queued": queued,
            "succeeded": succeeded,
            "failed": failed,
            "canceled": canceled,
            "total_jobs": len(self._jobs),
            "worker_running": self.is_running,
            "paused": self.paused,
        }

    async def _work(self) -> None:
        while True:
            job_id, handler, attempt = await self._queue.get()
            await self._resume_event.wait()
            job = self._jobs.get(job_id)
            if job is None:
                self._queue.task_done()
                continue
            if attempt != job.attempt:
                self._queue.task_done()
                continue
            if job.canceled:
                self._persist(job)
                self._queue.task_done()
                continue
            job.status = "running"
            job.started_at = time.time()
            self._persist(job)
            try:
                await handler(job)
                if job.canceled:
                    job.status = "canceled"
                    job.error = job.error or "Canceled by user."
                else:
                    job.status = "succeeded"
                    paths = self._storage.save_outputs(job.to_dict())
                    job.output_paths = {key: str(path) for key, path in paths.items()}
                    job.outputs = self._storage.output_urls(job.id)
            except Exception as exc:
                if job.canceled:
                    job.status = "canceled"
                    job.error = "Canceled by user."
                else:
                    job.status = "failed"
                    job.error = str(exc)
                    if job.documents:
                        paths = self._storage.save_outputs(job.to_dict())
                        job.output_paths = {key: str(path) for key, path in paths.items()}
                        job.outputs = self._storage.output_urls(job.id)
            finally:
                job.finished_at = time.time()
                self._persist(job)
                self._queue.task_done()

    def _persist(self, job: OCRJob) -> None:
        self._repository.upsert(job)

    def _load_persisted_jobs(self) -> None:
        for record in self._repository.list_recent(limit=self._max_recent_jobs):
            job = OCRJob.from_record(record, self._storage)
            if job.status == "running":
                job.status = "failed"
                job.error = job.error or "Service stopped while job was running."
                job.finished_at = time.time()
                self._repository.upsert(job)
            self._jobs[job.id] = job

    def _handler_from_source(self, job: OCRJob) -> JobHandler | None:
        return self._handlers.get(job.id)


async def process_image_batch_job(
    job: OCRJob,
    engine: Any,
    images: list[tuple[str, bytes]],
) -> None:
    job.total_units = len(images)
    for filename, image_bytes in images:
        if job.canceled:
            return
        items = await run_in_threadpool(engine.recognize, image_bytes)
        job.documents.append(
            OCRDocumentResult(
                filename=filename,
                pages=[OCRPageResult(page_number=1, text=_join_text(items), items=items)],
            )
        )
        job.completed_units += 1


async def process_pdf_job(
    job: OCRJob,
    engine: Any,
    filename: str,
    pdf_bytes: bytes,
    pdf_renderer: Callable[[bytes], list[bytes]],
) -> None:
    rendered_pages = await run_in_threadpool(pdf_renderer, pdf_bytes)
    job.total_units = len(rendered_pages)
    document = OCRDocumentResult(filename=filename)
    job.documents.append(document)

    for page_number, image_bytes in enumerate(rendered_pages, start=1):
        if job.canceled:
            return
        try:
            items = await run_in_threadpool(engine.recognize, image_bytes)
        except Exception as exc:
            document.pages.append(
                OCRPageResult(page_number=page_number, text="", items=[], error=str(exc))
            )
            job.completed_units += 1
            continue
        document.pages.append(
            OCRPageResult(page_number=page_number, text=_join_text(items), items=items)
        )
        job.completed_units += 1

    failed_pages = [page for page in document.pages if page.error is not None]
    if failed_pages:
        plural = "s" if len(failed_pages) != 1 else ""
        raise RuntimeError(f"{len(failed_pages)} page{plural} failed.")


def build_handler_from_source(
    source_payload: SourcePayload | None,
    engine: Any,
    pdf_renderer: Callable[[bytes], list[bytes]],
) -> JobHandler | None:
    if not source_payload:
        return None
    kind = source_payload.get("kind")
    if kind == "image_batch":
        images = [
            (item["filename"], bytes.fromhex(item["data_hex"]))
            for item in source_payload.get("images", [])
        ]

        async def image_handler(job: OCRJob) -> None:
            await process_image_batch_job(job, engine=engine, images=images)

        return image_handler
    if kind == "pdf":
        filename = source_payload["filename"]
        pdf_bytes = bytes.fromhex(source_payload["data_hex"])

        async def pdf_handler(job: OCRJob) -> None:
            await process_pdf_job(
                job,
                engine=engine,
                filename=filename,
                pdf_bytes=pdf_bytes,
                pdf_renderer=pdf_renderer,
            )

        return pdf_handler
    return None


def source_payload_for_images(images: list[tuple[str, bytes]]) -> SourcePayload:
    return {
        "kind": "image_batch",
        "images": [
            {
                "filename": filename,
                "data_hex": payload.hex(),
            }
            for filename, payload in images
        ],
    }


def source_payload_for_pdf(filename: str, pdf_bytes: bytes) -> SourcePayload:
    return {
        "kind": "pdf",
        "filename": filename,
        "data_hex": pdf_bytes.hex(),
    }


def _join_text(items: list[OCRItemDict]) -> str:
    return "\n".join(item["text"] for item in items)
