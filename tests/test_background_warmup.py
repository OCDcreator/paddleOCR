from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from paddleocr_service.engines.base import SupportedSetting
from paddleocr_service.main import create_app
from tests.helpers import make_settings


class _WarmingEngine:
    """Engine that flips is_ready to True after warm_up is awaited."""

    def __init__(self, settings) -> None:
        self.settings = settings
        self._ready = False
        self.warmup_called = False
        self.warmup_event = asyncio.Event()

    @property
    def name(self) -> str:
        return "warming"

    @property
    def is_ready(self) -> bool:
        return self._ready

    def warm_up(self) -> None:
        # Simulate a slow model load; the test releases this event to let it finish.
        self.warmup_called = True
        # Block (in the threadpool) until the test signals completion.
        import time

        deadline = time.time() + 5
        while not self.warmup_event.is_set() and time.time() < deadline:
            time.sleep(0.01)
        if self.warmup_event.is_set():
            self._ready = True

    def recognize(self, image_bytes: bytes) -> list: ...

    def apply_settings(self, **opts) -> dict:
        return opts

    def supported_settings(self) -> list[SupportedSetting]:
        return []

    def verify_available(self) -> None: ...


@pytest.mark.anyio
async def test_swap_returns_immediately_and_warms_in_background(tmp_path) -> None:
    import paddleocr_service.engines.registry as registry

    engine = _WarmingEngine(None)
    settings = make_settings(tmp_path)
    settings.engine = "rapidocr"
    registry.register("warming", lambda s: engine)
    transport = ASGITransport(app=create_app(ocr_engine=engine, settings=settings))

    async with AsyncClient(transport=transport, base_url="http://t") as client:
        # Swap to the warming engine. The PATCH must return immediately (engine
        # swapped) while the model load happens in the background.
        import time

        start = time.perf_counter()
        r = await client.patch("/settings", json={"engine": "warming"})
        elapsed = time.perf_counter() - start

        assert r.status_code == 200
        assert elapsed < 2.0, "PATCH must not block on warm_up"
        # The engine was installed but is NOT ready yet (warmup still running).
        health = await client.get("/health")
        assert health.json()["engine_ready"] is False

        # Let the background warmup finish, then poll until ready.
        engine.warmup_event.set()
        for _ in range(50):
            await asyncio.sleep(0.02)
            h = await client.get("/health")
            if h.json()["engine_ready"] is True:
                break
        else:
            pytest.fail("engine never became ready after background warmup")

    assert engine.warmup_called is True


@pytest.mark.anyio
async def test_health_reports_warmup_phase(tmp_path) -> None:
    import paddleocr_service.engines.registry as registry

    warming = _WarmingEngine(None)
    ready = _ReadyEngine()
    settings = make_settings(tmp_path)
    settings.engine = "rapidocr"
    registry.register("warming", lambda s: warming)
    registry.register("readyengine", lambda s: ready)
    transport = ASGITransport(app=create_app(ocr_engine=warming, settings=settings))

    async with AsyncClient(transport=transport, base_url="http://t") as client:
        # Before swap, no warmup in flight.
        h = (await client.get("/health")).json()
        assert h["warmup"]["phase"] == "idle"

        # Swap to a fresh warming engine -> phase should be "warming".
        await client.patch("/settings", json={"engine": "warming"})
        h = (await client.get("/health")).json()
        assert h["warmup"]["phase"] == "warming"
        assert h["warmup"]["engine"] == "warming"
        assert h["warmup"]["started_at"] is not None

        # Let it finish -> phase returns to idle.
        warming.warmup_event.set()
        for _ in range(50):
            await asyncio.sleep(0.02)
            h = (await client.get("/health")).json()
            if h["warmup"]["phase"] == "idle":
                break
        else:
            pytest.fail("phase never returned to idle")


@pytest.mark.anyio
async def test_swap_cancels_in_flight_warmup(tmp_path) -> None:
    import paddleocr_service.engines.registry as registry

    warming = _WarmingEngine(None)
    ready = _ReadyEngine()
    settings = make_settings(tmp_path)
    settings.engine = "rapidocr"
    registry.register("warming", lambda s: warming)
    registry.register("readyengine", lambda s: ready)
    transport = ASGITransport(app=create_app(ocr_engine=warming, settings=settings))

    async with AsyncClient(transport=transport, base_url="http://t") as client:
        # Start a warming warmup, then swap to a ready engine before it finishes.
        await client.patch("/settings", json={"engine": "warming"})
        # Warming's warmup is still blocked on its event (not yet set).
        await client.patch("/settings", json={"engine": "readyengine"})

        # After the second swap, phase must reflect the NEW engine, not the
        # cancelled warming one. ready is already ready so no warmup is started.
        h = (await client.get("/health")).json()
        assert h["warmup"]["phase"] == "idle"
        assert h["engine"] == "readyengine"
        assert h["engine_ready"] is True

    # The cancelled warming engine never became ready (its event was never set).
    assert warming.is_ready is False


class _ReadyEngine:
    """Engine that is immediately ready (no warmup needed)."""

    is_ready = True

    def __init__(self) -> None:
        pass

    @property
    def name(self) -> str:
        return "readyengine"

    def warm_up(self) -> None: ...

    def recognize(self, image_bytes: bytes) -> list: ...

    def apply_settings(self, **opts) -> dict:
        return opts

    def supported_settings(self) -> list:
        return []

    def verify_available(self) -> None: ...
