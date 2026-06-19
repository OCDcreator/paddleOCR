from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path

from httpx import AsyncClient
from PIL import Image

from paddleocr_service.config import Settings


class FakeEngine:
    is_ready = True

    def __init__(self, text_prefix: str = "text") -> None:
        self.text_prefix = text_prefix
        self.warmed = False
        self.calls = 0
        self.last_language: str | None = None
        self.last_use_angle_cls: bool | None = None

    def recognize(self, image_bytes: bytes):
        self.calls += 1
        return [
            {
                "text": f"{self.text_prefix}-{self.calls}-{len(image_bytes)}",
                "confidence": 0.99,
                "box": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
            }
        ]

    def warm_up(self) -> None:
        self.warmed = True

    def configure(self, language: str, use_angle_cls: bool) -> None:
        self.last_language = language
        self.last_use_angle_cls = use_angle_cls


class FlakyEngine(FakeEngine):
    def recognize(self, image_bytes: bytes):
        self.calls += 1
        if self.calls == 1:
            raise ValueError("synthetic OCR failure")
        return [
            {
                "text": "retry-ok",
                "confidence": 0.99,
                "box": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
            }
        ]


class SelectivelyFailingEngine(FakeEngine):
    def recognize(self, image_bytes: bytes):
        self.calls += 1
        if b"bad-page" in image_bytes:
            raise ValueError("page OCR failed")
        return [
            {
                "text": image_bytes.decode(errors="ignore"),
                "confidence": 0.99,
                "box": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
            }
        ]


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "database_path": tmp_path / "state" / "paddleocr.sqlite3",
        "output_dir": tmp_path / "outputs",
        "upload_dir": tmp_path / "uploads",
    }
    values.update(overrides)
    return Settings(**values)


def png_bytes(color: str = "white") -> bytes:
    image = Image.new("RGB", (80, 30), color=color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


async def wait_for_job(client: AsyncClient, job_id: str, attempts: int = 60) -> dict:
    for _ in range(attempts):
        response = await client.get(f"/jobs/{job_id}")
        response.raise_for_status()
        data = response.json()
        if data["status"] in {"succeeded", "failed", "canceled"}:
            return data
        await asyncio.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish")
