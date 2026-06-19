from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from paddleocr_service.main import create_app
from tests.helpers import FakeEngine, make_settings, png_bytes

pytestmark = pytest.mark.anyio


async def test_health_includes_operations_metadata(tmp_path) -> None:
    settings = make_settings(
        tmp_path,
        language="en",
        pdf_render_scale=2.5,
        save_uploads=True,
        max_upload_bytes=2048,
    )
    transport = ASGITransport(app=create_app(ocr_engine=FakeEngine(), settings=settings))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "0.1.0"
    assert data["settings"]["language"] == "en"
    assert data["settings"]["pdf_render_scale"] == 2.5
    assert data["settings"]["save_uploads"] is True
    assert data["storage"]["database_path"].endswith("paddleocr.sqlite3")
    assert data["storage"]["output_dir"].endswith("outputs")
    assert data["storage"]["output_bytes"] >= 0
    assert "model_cache_path" in data


async def test_settings_can_be_read_and_updated(tmp_path) -> None:
    settings = make_settings(tmp_path)
    engine = FakeEngine()
    transport = ASGITransport(app=create_app(ocr_engine=engine, settings=settings))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        initial = await client.get("/settings")
        update = await client.patch(
            "/settings",
            json={
                "language": "en",
                "pdf_render_scale": 3.0,
                "save_uploads": True,
                "warmup_on_startup": True,
                "retention_days": 14,
            },
        )
        reloaded = await client.get("/settings")

    assert initial.status_code == 200
    assert update.status_code == 200
    assert update.json()["language"] == "en"
    assert update.json()["pdf_render_scale"] == 3.0
    assert update.json()["save_uploads"] is True
    assert update.json()["retention_days"] == 14
    assert reloaded.json() == update.json()
    assert engine.last_language == "en"
    assert engine.last_use_angle_cls is True


async def test_warmup_endpoint_loads_model(tmp_path) -> None:
    settings = make_settings(tmp_path)
    engine = FakeEngine()
    transport = ASGITransport(app=create_app(ocr_engine=engine, settings=settings))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/operations/warmup")

    assert response.status_code == 200
    assert response.json()["ocr_loaded"] is True
    assert engine.warmed is True


async def test_upload_size_limit_is_enforced(tmp_path) -> None:
    settings = make_settings(tmp_path, max_upload_bytes=16)
    transport = ASGITransport(app=create_app(ocr_engine=FakeEngine(), settings=settings))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/jobs/images",
            files=[("images", ("too-big.png", png_bytes(), "image/png"))],
        )

    assert response.status_code == 413
    assert response.json()["detail"] == "Upload exceeds configured size limit."


async def test_batch_upload_size_limit_counts_total_request_bytes(tmp_path) -> None:
    settings = make_settings(tmp_path, max_upload_bytes=500)
    transport = ASGITransport(app=create_app(ocr_engine=FakeEngine(), settings=settings))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/jobs/images",
            files=[
                ("images", ("a.png", png_bytes(), "image/png")),
                ("images", ("b.png", png_bytes(), "image/png")),
            ],
        )

    assert response.status_code == 413
    assert response.json()["detail"] == "Upload exceeds configured size limit."


async def test_actual_image_and_pdf_content_are_validated(tmp_path) -> None:
    settings = make_settings(tmp_path)
    transport = ASGITransport(app=create_app(ocr_engine=FakeEngine(), settings=settings))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        bad_image = await client.post(
            "/jobs/images",
            files=[("images", ("fake.png", b"not a png", "image/png"))],
        )
        bad_pdf = await client.post(
            "/jobs/pdf",
            files={"pdf": ("fake.pdf", b"not a pdf", "application/pdf")},
        )

    assert bad_image.status_code == 400
    assert bad_image.json()["detail"] == "Uploaded file must be an image."
    assert bad_pdf.status_code == 400
    assert bad_pdf.json()["detail"] == "Uploaded file must be a valid PDF."


async def test_settings_update_rejects_invalid_ranges(tmp_path) -> None:
    settings = make_settings(tmp_path)
    transport = ASGITransport(app=create_app(ocr_engine=FakeEngine(), settings=settings))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        bad_upload_limit = await client.patch("/settings", json={"max_upload_bytes": 0})
        bad_pdf_scale = await client.patch("/settings", json={"pdf_render_scale": 0})
        bad_retention = await client.patch("/settings", json={"retention_days": -1})

    assert bad_upload_limit.status_code == 422
    assert bad_pdf_scale.status_code == 422
    assert bad_retention.status_code == 422


async def test_cors_preflight_uses_configured_allowed_origin(tmp_path) -> None:
    settings = make_settings(tmp_path, cors_origins=["http://phone.local"])
    transport = ASGITransport(app=create_app(ocr_engine=FakeEngine(), settings=settings))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        allowed = await client.options(
            "/jobs",
            headers={
                "Origin": "http://phone.local",
                "Access-Control-Request-Method": "GET",
            },
        )
        blocked = await client.options(
            "/jobs",
            headers={
                "Origin": "http://evil.local",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://phone.local"
    assert blocked.status_code == 400
