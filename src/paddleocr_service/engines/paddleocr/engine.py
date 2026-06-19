from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from paddleocr_service.config import Settings
from paddleocr_service.engines.base import OCRItemDict, SupportedSetting, validate_image
from paddleocr_service.engines.paddleocr.parser import parse_paddleocr_result

_SUPPORTED = [
    SupportedSetting(
        key="language", type="str", description="PaddleOCR language code (e.g. 'ch', 'en')."
    ),
    SupportedSetting(
        key="use_angle_cls",
        type="bool",
        description="Whether to run text-line orientation classification.",
    ),
]
_SUPPORTED_KEYS = {s.key for s in _SUPPORTED}


class UnsupportedSettingError(ValueError):
    """Raised by apply_settings for keys the engine does not accept."""


class PaddleOCREngine:
    """OCR engine backed by PaddleOCR. Implements the OCREngine protocol."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._ocr: Any | None = None

    @property
    def name(self) -> str:
        return "paddleocr"

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
            raw_result = ocr.predict(
                str(image_path),
                use_textline_orientation=self._settings.use_angle_cls,
            )
        finally:
            image_path.unlink(missing_ok=True)

        return parse_paddleocr_result(raw_result)

    def apply_settings(self, **opts: Any) -> dict[str, Any]:
        unknown = set(opts) - _SUPPORTED_KEYS
        if unknown:
            raise UnsupportedSettingError(
                f"paddleocr does not support setting(s): {sorted(unknown)}"
            )

        changed_model = False
        if "language" in opts and opts["language"] != self._settings.language:
            self._settings.language = opts["language"]
            changed_model = True
        if "use_angle_cls" in opts and opts["use_angle_cls"] != self._settings.use_angle_cls:
            self._settings.use_angle_cls = opts["use_angle_cls"]
            changed_model = True
        if changed_model:
            self._ocr = None  # force lazy reload on next recognize/warm_up

        return dict(opts)

    def supported_settings(self) -> list[SupportedSetting]:
        return list(_SUPPORTED)

    def _load_ocr(self) -> Any:
        if self._ocr is None:
            from paddleocr import PaddleOCR

            self._ocr = PaddleOCR(
                lang=self._settings.language,
                use_textline_orientation=self._settings.use_angle_cls,
            )
        return self._ocr
