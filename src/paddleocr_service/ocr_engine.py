from __future__ import annotations

import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from PIL import Image

from paddleocr_service.config import Settings

OCRItemDict = dict[str, Any]


def parse_paddleocr_result(raw_result: Any) -> list[OCRItemDict]:
    """Normalize common PaddleOCR result shapes to API OCR items."""
    if not raw_result:
        return []

    if isinstance(raw_result, list) and len(raw_result) == 1 and isinstance(raw_result[0], list):
        candidates: Iterable[Any] = raw_result[0]
    else:
        candidates = raw_result

    items: list[OCRItemDict] = []
    for candidate in candidates:
        parsed_items = _parse_candidate(candidate)
        for parsed in parsed_items:
            items.append(parsed)
    return items


def _parse_candidate(candidate: Any) -> list[OCRItemDict]:
    if isinstance(candidate, dict):
        return _parse_dict_candidate(candidate)

    if not isinstance(candidate, (list, tuple)) or len(candidate) < 2:
        return []

    box = _normalize_box(candidate[0])
    text_and_score = candidate[1]
    if not isinstance(text_and_score, (list, tuple)) or len(text_and_score) < 2:
        return []

    text = str(text_and_score[0])
    confidence = float(text_and_score[1])
    return [{"text": text, "confidence": confidence, "box": box}]


def _parse_dict_candidate(candidate: dict[str, Any]) -> list[OCRItemDict]:
    if "rec_texts" in candidate and "rec_scores" in candidate:
        # Use explicit `is None` checks, NOT `or` chains: PaddleOCR returns numpy
        # arrays here, and an empty array raises ValueError under boolean
        # conversion ("truth value of an empty array is ambiguous"). The `or`
        # operator coerces to bool, so it crashes on no-text results.
        boxes = _first_present(candidate, "rec_polys", "dt_polys", "rec_boxes")
        if boxes is None:
            return []

        return [
            {
                "text": str(text),
                "confidence": float(confidence),
                "box": _normalize_box(box),
            }
            for text, confidence, box in zip(
                candidate["rec_texts"],
                candidate["rec_scores"],
                boxes,
                strict=False,
            )
        ]

    text = _first_present(candidate, "text", "rec_text", "label")
    confidence = _first_present(candidate, "confidence", "score", "rec_score", "prob")
    box = _first_present(candidate, "box", "points", "dt_polys")
    if text is None or confidence is None or box is None:
        return []

    return [{"text": str(text), "confidence": float(confidence), "box": _normalize_box(box)}]


def _first_present(mapping: dict[str, Any], *keys: str) -> Any:
    """Return the first value for ``keys`` whose value is not ``None``.

    Unlike ``a or b or c``, this never coerces values to bool, so it is safe for
    numpy/ndarray values (which raise on boolean conversion). Returns ``None`` if
    no key is present (or all present values are ``None``).
    """
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None


def _normalize_box(box: Any) -> list[list[float]]:
    normalized: list[list[float]] = []
    for point in box:
        if hasattr(point, "tolist"):
            point = point.tolist()
        normalized.append([float(point[0]), float(point[1])])
    return normalized


class PaddleOCREngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._ocr: Any | None = None

    @property
    def is_ready(self) -> bool:
        return self._ocr is not None

    def warm_up(self) -> None:
        self._load_ocr()

    def configure(self, language: str, use_angle_cls: bool) -> None:
        if language != self._settings.language or use_angle_cls != self._settings.use_angle_cls:
            self._ocr = None
        self._settings.language = language
        self._settings.use_angle_cls = use_angle_cls

    def recognize(self, image_bytes: bytes) -> list[OCRItemDict]:
        self._validate_image(image_bytes)
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

    def _load_ocr(self) -> Any:
        if self._ocr is None:
            from paddleocr import PaddleOCR

            self._ocr = PaddleOCR(
                lang=self._settings.language,
                use_textline_orientation=self._settings.use_angle_cls,
            )
        return self._ocr

    @staticmethod
    def _validate_image(image_bytes: bytes) -> None:
        try:
            from io import BytesIO

            with Image.open(BytesIO(image_bytes)) as image:
                image.verify()
        except Exception as exc:
            raise ValueError("Uploaded file must be an image.") from exc
