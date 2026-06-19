from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from paddleocr_service.main import create_app
from tests.helpers import FakeEngine, make_settings, png_bytes, wait_for_job

pytestmark = pytest.mark.anyio


async def submit_one_image(client: AsyncClient) -> dict:
    response = await client.post(
        "/jobs/images",
        files=[("images", ("invoice.png", png_bytes(), "image/png"))],
    )
    assert response.status_code == 202
    return response.json()


async def complete_job(client: AsyncClient) -> dict:
    submitted = await submit_one_image(client)
    completed = await wait_for_job(client, submitted["id"])
    assert completed["status"] == "succeeded"
    return completed


async def test_completed_jobs_are_persisted_with_downloadable_outputs(tmp_path) -> None:
    settings = make_settings(tmp_path)
    transport = ASGITransport(app=create_app(ocr_engine=FakeEngine(), settings=settings))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        completed = await complete_job(client)
        job_id = completed["id"]

        assert completed["outputs"]["json"].endswith(f"/jobs/{job_id}/download/json")
        assert completed["outputs"]["txt"].endswith(f"/jobs/{job_id}/download/txt")
        assert completed["outputs"]["markdown"].endswith(f"/jobs/{job_id}/download/markdown")

        json_response = await client.get(f"/jobs/{job_id}/download/json")
        txt_response = await client.get(f"/jobs/{job_id}/download/txt")
        markdown_response = await client.get(f"/jobs/{job_id}/download/markdown")

    assert json_response.status_code == 200
    assert json_response.json()["id"] == job_id
    assert "text-1-" in txt_response.text
    assert "# OCR Job" in markdown_response.text
    assert (settings.output_dir / job_id / "result.json").exists()
    assert (settings.output_dir / job_id / "result.txt").exists()
    assert (settings.output_dir / job_id / "result.md").exists()
    assert not settings.upload_dir.exists()


async def test_history_survives_new_app_instance(tmp_path) -> None:
    settings = make_settings(tmp_path)

    first_transport = ASGITransport(app=create_app(ocr_engine=FakeEngine(), settings=settings))
    async with AsyncClient(transport=first_transport, base_url="http://testserver") as client:
        completed = await complete_job(client)
        job_id = completed["id"]

    second_transport = ASGITransport(app=create_app(ocr_engine=FakeEngine(), settings=settings))
    async with AsyncClient(transport=second_transport, base_url="http://testserver") as client:
        jobs_response = await client.get("/jobs")
        detail_response = await client.get(f"/jobs/{job_id}")
        download_response = await client.get(f"/jobs/{job_id}/download/txt")

    assert jobs_response.status_code == 200
    assert jobs_response.json()["jobs"][0]["id"] == job_id
    assert detail_response.status_code == 200
    assert detail_response.json()["status"] == "succeeded"
    assert download_response.status_code == 200
    assert "text-1-" in download_response.text


async def test_original_uploads_are_saved_only_when_enabled(tmp_path) -> None:
    settings = make_settings(tmp_path, save_uploads=True)
    transport = ASGITransport(app=create_app(ocr_engine=FakeEngine(), settings=settings))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        completed = await complete_job(client)

    upload_files = list((settings.upload_dir / completed["id"]).glob("*"))
    assert [path.name for path in upload_files] == ["invoice.png"]
