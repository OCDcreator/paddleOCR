from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from paddleocr_service.main import create_app
from tests.helpers import EngineProtocolMixin, make_settings


class _EngineMissingLib(EngineProtocolMixin):
    """An engine whose underlying library is not importable."""

    is_ready = True

    def verify_available(self) -> None:
        raise ModuleNotFoundError("No module named 'some_missing_lib'")


@pytest.mark.anyio
async def test_patch_settings_swap_to_missing_library_returns_422(tmp_path) -> None:
    # Default engine is the missing-lib one; swapping to rapidocr should work, but
    # here we swap FROM a present engine TO one whose library is missing.
    engine = _EngineMissingLib()
    settings = make_settings(tmp_path)
    settings.engine = "rapidocr"
    transport = ASGITransport(app=create_app(ocr_engine=engine, settings=settings))

    async with AsyncClient(transport=transport, base_url="http://t") as client:
        # Swap to "paddleocr" but force the registry to hand back a missing-lib engine.
        import paddleocr_service.engines.registry as registry

        orig = registry._ENGINES.get("paddleocr")
        registry.register("paddleocr", lambda s: _EngineMissingLib())
        try:
            r = await client.patch("/settings", json={"engine": "paddleocr"})
        finally:
            if orig is not None:
                registry.register("paddleocr", orig)

    assert r.status_code == 422
    assert "not available" in r.json()["detail"]


@pytest.mark.anyio
async def test_patch_settings_unknown_key_returns_422(tmp_path) -> None:
    engine = _EngineMissingLib()
    settings = make_settings(tmp_path)
    settings.engine = "rapidocr"
    transport = ASGITransport(app=create_app(ocr_engine=engine, settings=settings))

    async with AsyncClient(transport=transport, base_url="http://t") as client:
        # "language" is not a key this fake engine supports (it supports none).
        r = await client.patch("/settings", json={"language": "en"})

    assert r.status_code == 422
