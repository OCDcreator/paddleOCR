from __future__ import annotations

import pytest

from paddleocr_service.engines.base import (
    SupportedSetting,
    normalize_box,
    validate_image,
)


def test_supported_setting_stores_fields() -> None:
    s = SupportedSetting(key="language", type="str", description="OCR language")
    assert s.key == "language"
    assert s.type == "str"
    assert s.description == "OCR language"


def test_validate_image_accepts_png_bytes() -> None:
    # A real 1x1 PNG.
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    # Should not raise.
    validate_image(png)


def test_validate_image_rejects_non_image() -> None:
    with pytest.raises(ValueError, match="must be an image"):
        validate_image(b"not an image at all")


def test_normalize_box_flattens_and_floats() -> None:
    box = [[1, 2], [3, 4]]
    assert normalize_box(box) == [[1.0, 2.0], [3.0, 4.0]]


def test_normalize_box_handles_numpy_like_points() -> None:
    class FakePoint:
        def tolist(self) -> list[int]:
            return [5, 6]

    assert normalize_box([FakePoint()]) == [[5.0, 6.0]]
