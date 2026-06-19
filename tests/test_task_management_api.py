from __future__ import annotations

import asyncio
from threading import Event

import pytest
from httpx import ASGITransport, AsyncClient

from paddleocr_service.main import create_app
from tests.helpers import FakeEngine, FlakyEngine, make_settings, png_bytes, wait_for_job

pytestmark = pytest.mark.anyio


class BlockingEngine:
    is_ready = True

    def __init__(self) -> None:
        self.calls = 0
        self.release = Event()

    async def wait_until_called(self) -> None:
        for _ in range(40):
            if self.calls:
                return
            await asyncio.sleep(0.05)
        raise AssertionError("engine was not called")

    def recognize(self, image_bytes: bytes):
        self.calls += 1
        self.release.wait(timeout=5)
        return [
            {
                "text": "released",
                "confidence": 0.99,
                "box": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
            }
        ]


async def submit_image_job(client: AsyncClient, filename: str = "input.png") -> str:
    response = await client.post(
        "/jobs/images",
        files=[("images", (filename, png_bytes(), "image/png"))],
    )
    assert response.status_code == 202
    return response.json()["id"]


async def test_failed_job_can_be_retried_and_outputs_are_written(tmp_path) -> None:
    settings = make_settings(tmp_path)
    transport = ASGITransport(app=create_app(ocr_engine=FlakyEngine(), settings=settings))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        job_id = await submit_image_job(client)
        failed = await wait_for_job(client, job_id)
        retry_response = await client.post(f"/jobs/{job_id}/retry")
        retried = await wait_for_job(client, job_id)

    assert failed["status"] == "failed"
    assert failed["error"] == "synthetic OCR failure"
    assert retry_response.status_code == 202
    assert retry_response.json()["status"] == "queued"
    assert retried["status"] == "succeeded"
    assert retried["completed_units"] == 1
    assert (settings.output_dir / job_id / "result.json").exists()


async def test_queued_job_can_be_canceled_when_queue_is_paused(tmp_path) -> None:
    settings = make_settings(tmp_path)
    transport = ASGITransport(app=create_app(ocr_engine=FlakyEngine(), settings=settings))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        pause_response = await client.post("/queue/pause")
        job_id = await submit_image_job(client)
        cancel_response = await client.post(f"/jobs/{job_id}/cancel")
        canceled = await client.get(f"/jobs/{job_id}")

    assert pause_response.status_code == 200
    assert cancel_response.status_code == 200
    assert canceled.json()["status"] == "canceled"


async def test_canceled_queued_job_can_be_retried(tmp_path) -> None:
    settings = make_settings(tmp_path)
    transport = ASGITransport(app=create_app(ocr_engine=FakeEngine(), settings=settings))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/queue/pause")
        job_id = await submit_image_job(client)
        await client.post(f"/jobs/{job_id}/cancel")

        retry_response = await client.post(f"/jobs/{job_id}/retry")
        await client.post("/queue/resume")
        retried = await wait_for_job(client, job_id)

    assert retry_response.status_code == 202
    assert retried["status"] == "succeeded"
    assert retried["completed_units"] == 1


async def test_running_job_can_be_marked_canceled(tmp_path) -> None:
    settings = make_settings(tmp_path)
    engine = BlockingEngine()
    transport = ASGITransport(app=create_app(ocr_engine=engine, settings=settings))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        job_id = await submit_image_job(client)
        await engine.wait_until_called()
        cancel_response = await client.post(f"/jobs/{job_id}/cancel")
        engine.release.set()
        canceled = await wait_for_job(client, job_id)

    assert cancel_response.status_code == 200
    assert canceled["status"] == "canceled"


async def test_delete_job_removes_history_and_output_files(tmp_path) -> None:
    settings = make_settings(tmp_path)
    transport = ASGITransport(app=create_app(ocr_engine=FakeEngine("ok"), settings=settings))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        job_id = await submit_image_job(client)
        await wait_for_job(client, job_id)
        assert (settings.output_dir / job_id).exists()

        delete_response = await client.delete(f"/jobs/{job_id}")
        detail_response = await client.get(f"/jobs/{job_id}")

    assert delete_response.status_code == 200
    assert detail_response.status_code == 404
    assert not (settings.output_dir / job_id).exists()


async def test_queue_pause_and_resume_controls_processing(tmp_path) -> None:
    settings = make_settings(tmp_path)
    transport = ASGITransport(app=create_app(ocr_engine=FlakyEngine("ok"), settings=settings))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post("/queue/pause")
        job_id = await submit_image_job(client)
        queued = await client.get(f"/jobs/{job_id}")
        health_while_paused = await client.get("/health")

        await client.post("/queue/resume")
        finished = await wait_for_job(client, job_id)
        health_after_resume = await client.get("/health")

    assert queued.json()["status"] == "queued"
    assert health_while_paused.json()["queue"]["paused"] is True
    assert finished["status"] in {"succeeded", "failed"}
    assert health_after_resume.json()["queue"]["paused"] is False
