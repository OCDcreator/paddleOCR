from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from paddleocr_service.main import create_app
from tests.helpers import EngineProtocolMixin, make_settings


class _FakeEngine(EngineProtocolMixin):
    is_ready = True


@pytest.mark.anyio
async def test_engines_endpoint_lists_registered_and_current(tmp_path) -> None:
    settings = make_settings(tmp_path)
    settings.engine = "rapidocr"
    transport = ASGITransport(app=create_app(ocr_engine=_FakeEngine(), settings=settings))

    async with AsyncClient(transport=transport, base_url="http://t") as client:
        response = await client.get("/engines")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["engines"], list)
    # Both built-in engines are registered.
    assert "rapidocr" in data["engines"]
    assert "paddleocr" in data["engines"]
    assert data["current"] == "rapidocr"
