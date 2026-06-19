import asyncio
from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from paddleocr_service.main import create_app
from tests.helpers import make_settings


class FakeEngine:
    is_ready = True

    def recognize(self, image_bytes: bytes):
        return [
            {
                "text": f"image-{len(image_bytes)}",
                "confidence": 0.99,
                "box": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
            }
        ]


def png_bytes(color: str = "white") -> bytes:
    image = Image.new("RGB", (80, 30), color=color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def wait_for_job(client: AsyncClient, job_id: str) -> dict:
    for _ in range(20):
        response = await client.get(f"/jobs/{job_id}")
        response.raise_for_status()
        data = response.json()
        if data["status"] in {"succeeded", "failed"}:
            return data
        await asyncio.sleep(0.05)
    raise AssertionError("job did not finish")


@pytest.mark.anyio
async def test_batch_images_are_queued_and_processed() -> None:
    transport = ASGITransport(app=create_app(ocr_engine=FakeEngine()))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/jobs/images",
            files=[
                ("images", ("a.png", png_bytes("white"), "image/png")),
                ("images", ("b.png", png_bytes("yellow"), "image/png")),
            ],
        )

        assert response.status_code == 202
        submitted = response.json()
        assert submitted["status"] == "queued"
        assert submitted["kind"] == "image_batch"
        assert submitted["total_units"] == 2

        completed = await wait_for_job(client, submitted["id"])

    assert completed["status"] == "succeeded"
    assert completed["completed_units"] == 2
    assert len(completed["documents"]) == 2
    assert completed["documents"][0]["filename"] == "a.png"
    assert completed["documents"][0]["pages"][0]["text"].startswith("image-")


@pytest.mark.anyio
async def test_jobs_list_includes_recent_jobs_and_health_reports_queue(tmp_path) -> None:
    transport = ASGITransport(
        app=create_app(ocr_engine=FakeEngine(), settings=make_settings(tmp_path))
    )

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        submitted = (
            await client.post(
                "/jobs/images",
                files=[("images", ("a.png", png_bytes(), "image/png"))],
            )
        ).json()
        await wait_for_job(client, submitted["id"])

        jobs_response = await client.get("/jobs")
        health_response = await client.get("/health")

    assert jobs_response.status_code == 200
    assert jobs_response.json()["jobs"][0]["id"] == submitted["id"]
    assert health_response.status_code == 200
    assert health_response.json()["queue"]["total_jobs"] == 1
