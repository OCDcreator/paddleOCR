from __future__ import annotations

import time
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from paddleocr_service.config import Settings
from paddleocr_service.database import JobRepository
from paddleocr_service.storage import LocalStorage


class AccessLogMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, settings: Settings) -> None:
        super().__init__(app)
        self._settings = settings

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        started = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        self._write_line(
            f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} "
            f"{request.client.host if request.client else '-'} "
            f"{request.method} {request.url.path} "
            f"{response.status_code} {elapsed_ms}ms\n"
        )
        return response

    def _write_line(self, line: str) -> None:
        self._settings.access_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._settings.access_log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(line)


def cleanup_expired_jobs(
    settings: Settings,
    repository: JobRepository,
    storage: LocalStorage,
) -> dict[str, Any]:
    if settings.retention_days <= 0:
        return {
            "deleted_jobs": 0,
            "retention_days": settings.retention_days,
            "job_ids": [],
        }

    cutoff = time.time() - (settings.retention_days * 24 * 60 * 60)
    expired_jobs = repository.list_expired(cutoff)
    for job in expired_jobs:
        repository.delete(job["id"])
        storage.delete_job_files(job["id"])

    return {
        "deleted_jobs": len(expired_jobs),
        "retention_days": settings.retention_days,
        "job_ids": [job["id"] for job in expired_jobs],
    }
