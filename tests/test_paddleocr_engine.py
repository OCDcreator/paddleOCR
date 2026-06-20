from __future__ import annotations

import pytest

from paddleocr_service.engines.base import SupportedSetting
from paddleocr_service.engines.paddleocr.engine import (
    PaddleOCREngine,
    UnsupportedSettingError,
)


def _settings(**overrides):
    from paddleocr_service.config import Settings

    base = {"database_path": "/tmp/x.sqlite3", "output_dir": "/tmp/out", "upload_dir": "/tmp/up"}
    base.update(overrides)
    return Settings(**base)


def test_engine_name() -> None:
    assert PaddleOCREngine(_settings()).name == "paddleocr"


def test_apply_settings_accepts_language_and_use_angle_cls() -> None:
    eng = PaddleOCREngine(_settings(language="ch"))
    result = eng.apply_settings(language="en", use_angle_cls=False)
    assert result == {"language": "en", "use_angle_cls": False}


def test_apply_settings_unknown_key_raises() -> None:
    eng = PaddleOCREngine(_settings())
    with pytest.raises(UnsupportedSettingError):
        eng.apply_settings(bogus_key=1)


def test_supported_settings_lists_language_and_use_angle_cls() -> None:
    eng = PaddleOCREngine(_settings())
    keys = {s.key for s in eng.supported_settings()}
    assert {"language", "use_angle_cls"} <= keys
    assert all(isinstance(s, SupportedSetting) for s in eng.supported_settings())


def test_apply_settings_language_change_marks_not_ready() -> None:
    eng = PaddleOCREngine(_settings(language="ch"))
    # changing language must invalidate the loaded model (lazy reload) without
    # actually loading the heavy paddleocr library.
    eng.apply_settings(language="en")
    assert eng.is_ready is False
