import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from paddleocr_service.main import create_app
from tests.helpers import SelectivelyFailingEngine, make_settings


class FakeEngine:
    is_ready = True

    def recognize(self, image_bytes: bytes):
        return [
            {
                "text": image_bytes.decode(),
                "confidence": 0.97,
                "box": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
            }
        ]


def fake_pdf_renderer(pdf_bytes: bytes) -> list[bytes]:
    assert pdf_bytes == b"%PDF fake"
    return [b"page one", b"page two"]


def partially_bad_pdf_renderer(pdf_bytes: bytes) -> list[bytes]:
    assert pdf_bytes == b"%PDF partial"
    return [b"good-page", b"bad-page", b"final-page"]


async def wait_for_job(client: AsyncClient, job_id: str) -> dict:
    for _ in range(20):
        response = await client.get(f"/jobs/{job_id}")
        response.raise_for_status()
        data = response.json()
        if data["status"] in {"succeeded", "failed"}:
            return data
        await asyncio.sleep(0.05)
    raise AssertionError("job did not finish")


@pytest.mark.anyio
async def test_pdf_is_queued_rendered_and_processed_page_by_page() -> None:
    transport = ASGITransport(
        app=create_app(ocr_engine=FakeEngine(), pdf_renderer=fake_pdf_renderer)
    )

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/jobs/pdf",
            files={"pdf": ("doc.pdf", b"%PDF fake", "application/pdf")},
        )

        assert response.status_code == 202
        submitted = response.json()
        assert submitted["kind"] == "pdf"
        assert submitted["total_units"] == 1

        completed = await wait_for_job(client, submitted["id"])

    assert completed["status"] == "succeeded"
    assert completed["total_units"] == 2
    assert completed["completed_units"] == 2
    assert completed["documents"] == [
        {
            "filename": "doc.pdf",
            "pages": [
                {
                    "page_number": 1,
                    "text": "page one",
                    "items": [
                        {
                            "text": "page one",
                            "confidence": 0.97,
                            "box": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
                        }
                    ],
                },
                {
                    "page_number": 2,
                    "text": "page two",
                    "items": [
                        {
                            "text": "page two",
                            "confidence": 0.97,
                            "box": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
                        }
                    ],
                },
            ],
        }
    ]


@pytest.mark.anyio
async def test_pdf_upload_rejects_non_pdf_content_type() -> None:
    transport = ASGITransport(
        app=create_app(ocr_engine=FakeEngine(), pdf_renderer=fake_pdf_renderer)
    )

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/jobs/pdf",
            files={"pdf": ("doc.txt", b"hello", "text/plain")},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Uploaded file must be a PDF."


@pytest.mark.anyio
async def test_pdf_page_failures_keep_successful_pages_and_mark_job_failed(tmp_path) -> None:
    transport = ASGITransport(
        app=create_app(
            ocr_engine=SelectivelyFailingEngine(),
            settings=make_settings(tmp_path),
            pdf_renderer=partially_bad_pdf_renderer,
        )
    )

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/jobs/pdf",
            files={"pdf": ("partial.pdf", b"%PDF partial", "application/pdf")},
        )
        submitted = response.json()
        completed = await wait_for_job(client, submitted["id"])
        txt_response = await client.get(f"/jobs/{submitted['id']}/download/txt")

    assert completed["status"] == "failed"
    assert completed["completed_units"] == 3
    assert completed["error"] == "1 page failed."
    pages = completed["documents"][0]["pages"]
    assert pages[0]["text"] == "good-page"
    assert pages[1]["error"] == "page OCR failed"
    assert pages[2]["text"] == "final-page"
    assert txt_response.status_code == 200
    assert "good-page" in txt_response.text
    assert "final-page" in txt_response.text
