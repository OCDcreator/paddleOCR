# Queue UI Verification - 2026-06-17

Environment:
- Service bind: `0.0.0.0:8866`
- Frontend URL: `http://127.0.0.1:8866/`
- OCR model files: cached in `/Users/dht/.paddlex/official_models`

Automated checks:

```bash
uv run --extra dev pytest -q
```

Result:

```text
13 passed in 0.75s
```

```bash
uv run ruff check .
```

Result:

```text
All checks passed!
```

Functional check:

```bash
uv run python scripts/create_sample_image.py
uv run python scripts/create_sample_pdf.py
uv run python scripts/functional_check.py
```

Result:

```json
{
  "health": {
    "status": "ok",
    "ocr_loaded": false,
    "queue": {
      "running": 0,
      "queued": 0,
      "succeeded": 0,
      "failed": 0,
      "total_jobs": 0,
      "worker_running": true
    }
  },
  "single_text": "PaddleOCR LAN Test\nInvoice No: OCR-8866\nAmount: 123.45 USD",
  "batch_status": "succeeded",
  "batch_documents": 2,
  "pdf_status": "succeeded",
  "pdf_pages": 2
}
```

Browser check:
- Opened `http://127.0.0.1:8866/`.
- Confirmed the page renders `PaddleOCR LAN Console`.
- Confirmed health panel showed `ok`, model loaded state, queue counts, and job counts.
- Confirmed controls exist for single image, batch images, and PDF.
- Clicked a completed PDF job and confirmed the result panel rendered both OCR pages.

Observed PDF OCR text:

```text
PaddleOCR PDF Page 1
Batch Code: PDF-001
PaddleOCR PDF Page 2
Total: 678.90 USD
```

Conclusion:
- Frontend, health panel, batch image jobs, PDF jobs, queue processing, job polling, and static serving are functional.
- The queue is in-memory and suitable for the current single-machine LAN deployment.
