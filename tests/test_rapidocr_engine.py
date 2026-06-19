from __future__ import annotations

import pytest

from paddleocr_service.config import Settings
from paddleocr_service.engines.base import SupportedSetting
from paddleocr_service.engines.rapidocr.engine import (
    RapidOCREngine,
    UnsupportedSettingError,
)
from paddleocr_service.engines.rapidocr.parser import normalize_rapidocr_result


def _settings() -> Settings:
    return Settings(database_path="/tmp/x.sqlite3", output_dir="/tmp/o", upload_dir="/tmp/u")


def test_engine_name() -> None:
    eng = RapidOCREngine(_settings())
    assert eng.name == "rapidocr"
    assert eng.is_ready is False


def test_parser_unpacks_lines_elapse_tuple() -> None:
    # shape: (lines, elapse) where lines = [ [box, text, score], ... ]
    box = [[1, 2], [10, 2], [10, 8], [1, 8]]
    result = ([[box, "hello", 0.97]], [0.4])
    items = normalize_rapidocr_result(result)
    assert items == [
        {
            "text": "hello",
            "confidence": 0.97,
            "box": [[1.0, 2.0], [10.0, 2.0], [10.0, 8.0], [1.0, 8.0]],
        }
    ]


def test_parser_handles_none() -> None:
    assert normalize_rapidocr_result(None) == []


def test_apply_settings_unknown_key_raises() -> None:
    eng = RapidOCREngine(_settings())
    with pytest.raises(UnsupportedSettingError):
        eng.apply_settings(language="en")  # language is a PaddleOCR key, not RapidOCR's


def test_supported_settings_returns_supported_setting_objects() -> None:
    eng = RapidOCREngine(_settings())
    settings = eng.supported_settings()
    assert all(isinstance(s, SupportedSetting) for s in settings)


class _FakeRapidOCR:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs

    def __call__(self, path):
        # shape: (lines, elapse) where lines = [ [box, text, score], ... ]
        box = [[1, 2], [3, 4], [5, 6], [7, 8]]
        return ([[box, "hi", 0.9]], [0.1])


def test_recognize_uses_injected_rapidocr() -> None:
    eng = RapidOCREngine(_settings())
    # Bypass the real rapidocr_onnxruntime import in _load_ocr.
    eng._load_ocr = lambda: _FakeRapidOCR()  # type: ignore[assignment]
    items = eng.recognize(_png_bytes())
    assert items == [
        {"text": "hi", "confidence": 0.9, "box": [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0], [7.0, 8.0]]}
    ]


def _png_bytes() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
