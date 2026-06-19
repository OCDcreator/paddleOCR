from __future__ import annotations

import pytest

from paddleocr_service.engines import registry
from paddleocr_service.engines.base import OCREngine, SupportedSetting


class _FakeEngine:
    name = "fake"

    def __init__(self, settings) -> None:
        self.settings = settings

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


def test_available_engines_is_a_list_of_strings() -> None:
    names = registry.available_engines()
    assert isinstance(names, list)
    assert all(isinstance(n, str) for n in names)
    # Both engines are registered by name in the spec.
    assert "rapidocr" in names
    assert "paddleocr" in names


def test_create_engine_unknown_name_raises() -> None:
    with pytest.raises(ValueError, match="unknown engine"):
        registry.create_engine("does-not-exist", settings=None)


def test_register_and_create_custom_engine() -> None:
    registry.register("fake", _FakeEngine)
    eng = registry.create_engine("fake", settings={"x": 1})
    assert isinstance(eng, _FakeEngine)
    assert eng.settings == {"x": 1}


def test_fake_engine_satisfies_protocol() -> None:
    # Sanity: the fake we use for tests structurally satisfies OCREngine.
    assert isinstance(_FakeEngine(settings=None), OCREngine)
