import asyncio
import time
from io import BytesIO

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image

from paddleocr_service.main import create_app


class SlowEngine:
    is_ready = True

    def recognize(self, image_bytes: bytes):
        time.sleep(0.2)
        return [
            {
                "text": "ok",
                "confidence": 0.99,
                "box": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
            }
        ]


def png_bytes() -> bytes:
    image = Image.new("RGB", (80, 30), color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.mark.anyio
async def test_ocr_recognition_does_not_block_event_loop() -> None:
    transport = ASGITransport(app=create_app(ocr_engine=SlowEngine()))

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        started = time.perf_counter()
        responses = await asyncio.gather(
            client.post("/ocr", files={"image": ("a.png", png_bytes(), "image/png")}),
            client.post("/ocr", files={"image": ("b.png", png_bytes(), "image/png")}),
        )
        elapsed = time.perf_counter() - started

    assert [response.status_code for response in responses] == [200, 200]
    assert elapsed < 0.35
