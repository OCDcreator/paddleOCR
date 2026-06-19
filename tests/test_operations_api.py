from __future__ import annotations

import time

import pytest
from httpx import ASGITransport, AsyncClient

from paddleocr_service.database import JobRepository
from paddleocr_service.main import create_app
from tests.helpers import FakeEngine, make_settings, png_bytes, wait_for_job

pytestmark = pytest.mark.anyio


async def _completed_job(client: AsyncClient) -> dict:
    response = await client.post(
        "/jobs/images",
        files=[("images", ("old.png", png_bytes(), "image/png"))],
    )
    response.raise_for_status()
    return await wait_for_job(client, response.json()["id"])


async def test_retention_cleanup_removes_expired_jobs_and_outputs(tmp_path) -> None:
    settings = make_settings(tmp_path, retention_days=1)
    transport = ASGITransport(app=create_app(ocr_engine=FakeEngine(), settings=settings))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        completed = await _completed_job(client)
        job_id = completed["id"]

    repository = JobRepository(settings.database_path)
    expired_time = time.time() - (3 * 24 * 60 * 60)
    with repository._connect() as connection:
        connection.execute(
            "UPDATE jobs SET created_at = ?, finished_at = ? WHERE id = ?",
            (expired_time, expired_time, job_id),
        )

    second_transport = ASGITransport(app=create_app(ocr_engine=FakeEngine(), settings=settings))
    async with AsyncClient(transport=second_transport, base_url="http://testserver") as client:
        response = await client.post("/operations/retention/cleanup")
        detail = await client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    assert response.json()["deleted_jobs"] == 1
    assert detail.status_code == 404
    assert not (settings.output_dir / job_id).exists()


async def test_access_log_records_request_without_ocr_text(tmp_path) -> None:
    settings = make_settings(tmp_path, access_log_path=tmp_path / "logs" / "access.log")
    transport = ASGITransport(app=create_app(ocr_engine=FakeEngine(), settings=settings))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.get("/health")

    log_text = settings.access_log_path.read_text(encoding="utf-8")
    assert "GET /health" in log_text
    assert "PaddleOCR LAN Test" not in log_text
