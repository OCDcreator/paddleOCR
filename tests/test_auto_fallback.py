from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from paddleocr_service.engines.base import SupportedSetting
from paddleocr_service.main import create_app
from tests.helpers import make_settings


class _GoodEngine:
    """Engine that is ready immediately and never fails."""

    def __init__(self, settings=None) -> None:
        self.settings = settings

    @property
    def name(self) -> str:
        return "good"

    @property
    def is_ready(self) -> bool:
        return True

    def warm_up(self) -> None: ...

    def recognize(self, image_bytes: bytes) -> list: ...

    def apply_settings(self, **opts) -> dict:
        return opts

    def supported_settings(self) -> list[SupportedSetting]:
        return []

    def verify_available(self) -> None: ...


class _FailingEngine:
    """Engine whose warm_up always raises, and is_ready only after a successful warm."""

    def __init__(self, settings=None) -> None:
        self.settings = settings
        self._ready = False

    @property
    def name(self) -> str:
        return "failing"

    @property
    def is_ready(self) -> bool:
        return self._ready

    def warm_up(self) -> None:
        raise RuntimeError("model load exploded")

    def recognize(self, image_bytes: bytes) -> list: ...

    def apply_settings(self, **opts) -> dict:
        return opts

    def supported_settings(self) -> list[SupportedSetting]:
        return []

    def verify_available(self) -> None: ...


@pytest.mark.anyio
async def test_warmup_failure_rolls_back_to_known_good_engine(tmp_path) -> None:
    import paddleocr_service.engines.registry as registry

    good = _GoodEngine()
    settings = make_settings(tmp_path)
    settings.engine = "good"
    registry.register("good", lambda s: good)
    registry.register("failing", lambda s: _FailingEngine(s))
    # Start with the good engine installed and ready.
    transport = ASGITransport(app=create_app(ocr_engine=good, settings=settings))

    async with AsyncClient(transport=transport, base_url="http://t") as client:
        # Sanity: live engine is good and ready.
        assert (await client.get("/health")).json()["engine"] == "good"

        # Swap to the failing engine. verify_available passes (it's a fake), so the
        # swap commits and a background warmup starts; that warmup raises.
        r = await client.patch("/settings", json={"engine": "failing"})
        assert r.status_code == 200

        # Poll until the background warmup has run and triggered auto-fallback.
        rolled_back = False
        for _ in range(50):
            await asyncio.sleep(0.02)
            h = (await client.get("/health")).json()
            if h["engine"] == "good":
                rolled_back = True
                break
        assert rolled_back, "engine did not roll back to known-good after warmup failure"

        # After rollback: live engine is good, phase is idle (not failed), ready True.
        h = (await client.get("/health")).json()
        assert h["engine"] == "good"
        assert h["engine_ready"] is True
        assert h["warmup"]["phase"] == "idle"


@pytest.mark.anyio
async def test_no_fallback_when_no_known_good_engine(tmp_path) -> None:
    """If the prior engine was never ready, a failed warmup does not roll back."""
    import paddleocr_service.engines.registry as registry

    good = _GoodEngine()
    settings = make_settings(tmp_path)
    # Start cold: engine is NOT ready (so no known-good target is recorded).
    failing = _FailingEngine()
    settings.engine = "failing"
    registry.register("good", lambda s: good)
    registry.register("failing", lambda s: failing)
    transport = ASGITransport(app=create_app(ocr_engine=failing, settings=settings))

    async with AsyncClient(transport=transport, base_url="http://t") as client:
        # Swap to good (good is ready, so this records good as known-good). Then
        # immediately swap to failing again — but the failing warmup should roll
        # back to good now. Instead, test the no-target case directly: start fresh
        # with failing as the only engine and ensure a failed warmup stays failed.
        # (This test documents that with no known-good, phase stays "failed".)
        # Trigger a manual swap to a fresh failing instance to force a warmup.
        registry.register("failing2", lambda s: _FailingEngine(s))
        await client.patch("/settings", json={"engine": "failing2"})
        await asyncio.sleep(0.1)
        h = (await client.get("/health")).json()
        # No prior ready engine was recorded (initial failing was not ready), so
        # the failed warmup cannot roll back: phase stays failed, engine stays failing2.
        assert h["engine"] == "failing2"
        assert h["warmup"]["phase"] == "failed"
