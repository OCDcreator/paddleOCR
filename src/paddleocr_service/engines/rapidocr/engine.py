from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from paddleocr_service.config import Settings
from paddleocr_service.engines.base import OCRItemDict, SupportedSetting, validate_image
from paddleocr_service.engines.rapidocr.parser import normalize_rapidocr_result

# Verified against rapidocr_onnxruntime's RapidOCR() constructor. text_score is
# the recognition confidence threshold. Adjust if a future version renames it.
_SUPPORTED = [
    SupportedSetting(
        key="text_score",
        type="float",
        description="Recognition confidence threshold (0.0-1.0).",
    ),
]
_SUPPORTED_KEYS = {s.key for s in _SUPPORTED}


class UnsupportedSettingError(ValueError):
    """Raised by apply_settings for keys the engine does not accept."""


class RapidOCREngine:
    """OCR engine backed by RapidOCR (ONNX Runtime). Implements OCREngine."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._ocr: Any | None = None
        self._pending_opts: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return "rapidocr"

    @property
    def is_ready(self) -> bool:
        return self._ocr is not None

    def warm_up(self) -> None:
        self._load_ocr()

    def recognize(self, image_bytes: bytes) -> list[OCRItemDict]:
        validate_image(image_bytes)
        ocr = self._load_ocr()

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as image_file:
            image_file.write(image_bytes)
            image_path = Path(image_file.name)
        try:
            raw = ocr(str(image_path))
        finally:
            image_path.unlink(missing_ok=True)

        return normalize_rapidocr_result(raw)

    def apply_settings(self, **opts: Any) -> dict[str, Any]:
        unknown = set(opts) - _SUPPORTED_KEYS
        if unknown:
            raise UnsupportedSettingError(
                f"rapidocr does not support setting(s): {sorted(unknown)}"
            )
        # RapidOCR settings require a model rebuild, so invalidate the loaded
        # model and stash the options to apply on next _load_ocr.
        if opts:
            self._ocr = None
            self._pending_opts = dict(opts)
        return dict(opts)

    def supported_settings(self) -> list[SupportedSetting]:
        return list(_SUPPORTED)

    def _load_ocr(self) -> Any:
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR

            self._ocr = RapidOCR(**self._pending_opts)
        return self._ocr
