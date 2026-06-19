from __future__ import annotations

from io import BytesIO
from typing import Any, Protocol, runtime_checkable

from PIL import Image

OCRItemDict = dict[str, Any]


@runtime_checkable
class OCREngine(Protocol):
    """Unified OCR engine interface. Implementations: PaddleOCR, RapidOCR."""

    @property
    def name(self) -> str: ...

    @property
    def is_ready(self) -> bool: ...

    def warm_up(self) -> None: ...

    def recognize(self, image_bytes: bytes) -> list[OCRItemDict]: ...

    def apply_settings(self, **opts: Any) -> dict[str, Any]: ...

    def supported_settings(self) -> list[SupportedSetting]: ...

    def verify_available(self) -> None: ...


class SupportedSetting:
    """Declares one configurable key an engine accepts via apply_settings."""

    def __init__(self, key: str, type: str, description: str) -> None:
        self.key = key
        self.type = type
        self.description = description


def validate_image(image_bytes: bytes) -> None:
    """Raise ValueError if the bytes are not a valid image."""
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()
    except Exception as exc:
        raise ValueError("Uploaded file must be an image.") from exc


def normalize_box(box: Any) -> list[list[float]]:
    """Normalize a box (list of points, possibly numpy) to list[list[float]]."""
    normalized: list[list[float]] = []
    for point in box:
        if hasattr(point, "tolist"):
            point = point.tolist()
        normalized.append([float(point[0]), float(point[1])])
    return normalized
