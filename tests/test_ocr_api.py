from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from paddleocr_service.main import create_app


class FakeEngine:
    is_ready = True

    @property
    def name(self) -> str:
        return "fake"

    def recognize(self, image_bytes: bytes):
        self.last_image_bytes = image_bytes
        return [
            {
                "text": "hello",
                "confidence": 0.98,
                "box": [[1.0, 2.0], [20.0, 2.0], [20.0, 12.0], [1.0, 12.0]],
            },
            {
                "text": "world",
                "confidence": 0.95,
                "box": [[1.0, 15.0], [30.0, 15.0], [30.0, 25.0], [1.0, 25.0]],
            },
        ]

    def warm_up(self) -> None:
        pass

    def apply_settings(self, **opts):
        return opts

    def supported_settings(self):
        return []

    def verify_available(self) -> None:
        pass


def png_bytes() -> bytes:
    image = Image.new("RGB", (80, 30), color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.anyio
async def test_ocr_accepts_one_image_and_returns_text_items_and_elapsed_time() -> None:
    engine = FakeEngine()
    transport = ASGITransport(app=create_app(ocr_engine=engine))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/ocr",
            files={"image": ("sample.png", png_bytes(), "image/png")},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["text"] == "hello\nworld"
    assert data["items"] == [
        {
            "text": "hello",
            "confidence": 0.98,
            "box": [[1.0, 2.0], [20.0, 2.0], [20.0, 12.0], [1.0, 12.0]],
        },
        {
            "text": "world",
            "confidence": 0.95,
            "box": [[1.0, 15.0], [30.0, 15.0], [30.0, 25.0], [1.0, 25.0]],
        },
    ]
    assert isinstance(data["elapsed_ms"], int)
    assert data["elapsed_ms"] >= 0
    assert engine.last_image_bytes.startswith(b"\x89PNG")


@pytest.mark.anyio
async def test_ocr_rejects_non_image_upload() -> None:
    transport = ASGITransport(app=create_app(ocr_engine=FakeEngine()))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/ocr",
            files={"image": ("notes.txt", b"not an image", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Uploaded file must be an image."
