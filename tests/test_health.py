import pytest
from httpx import ASGITransport, AsyncClient

from paddleocr_service.main import create_app
from tests.helpers import make_settings


class ReadyEngine:
    is_ready = True


@pytest.mark.anyio
async def test_health_reports_loaded_engine(tmp_path) -> None:
    transport = ASGITransport(
        app=create_app(ocr_engine=ReadyEngine(), settings=make_settings(tmp_path))
    )

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["ocr_loaded"] is True
    assert data["queue"]["total_jobs"] == 0
