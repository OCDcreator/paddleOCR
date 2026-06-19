# Batch PDF Queue UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a static frontend, richer health check, batch image jobs, PDF jobs, and an in-memory OCR queue to the existing PaddleOCR LAN service.

**Architecture:** Keep `/ocr` as a synchronous compatibility endpoint. Add an in-process `OCRJobQueue` with one background worker, reusable document processing functions, PDF rendering via `pypdfium2`, and no-build static assets served by FastAPI.

**Tech Stack:** Python 3.11-3.13, FastAPI, Pillow, pypdfium2, PaddleOCR, pytest, httpx, plain HTML/CSS/JavaScript.

---

### Task 1: Queue and Document Models

**Files:**
- Create: `src/paddleocr_service/jobs.py`
- Modify: `src/paddleocr_service/schemas.py`
- Test: `tests/test_jobs.py`

- [ ] Write failing tests for queue submission, job lifecycle, and result shape using a fake OCR processor.
- [ ] Implement `JobStatus`, `OCRDocumentResult`, `OCRJob`, and `OCRJobQueue`.
- [ ] Run `uv run --extra dev pytest tests/test_jobs.py -q`.

### Task 2: Batch Image API

**Files:**
- Modify: `src/paddleocr_service/main.py`
- Test: `tests/test_batch_api.py`

- [ ] Write failing tests for `POST /jobs/images`, `GET /jobs/{id}`, and `GET /jobs`.
- [ ] Implement batch image upload validation and job submission.
- [ ] Run `uv run --extra dev pytest tests/test_batch_api.py -q`.

### Task 3: PDF API

**Files:**
- Create: `src/paddleocr_service/pdf.py`
- Modify: `src/paddleocr_service/jobs.py`
- Modify: `src/paddleocr_service/main.py`
- Test: `tests/test_pdf_api.py`

- [ ] Write failing tests for PDF submission using an injected fake PDF renderer.
- [ ] Implement PDF rendering through `pypdfium2` and route injection for tests.
- [ ] Run `uv run --extra dev pytest tests/test_pdf_api.py -q`.

### Task 4: Frontend

**Files:**
- Create: `src/paddleocr_service/static/index.html`
- Create: `src/paddleocr_service/static/styles.css`
- Create: `src/paddleocr_service/static/app.js`
- Modify: `src/paddleocr_service/main.py`
- Test: `tests/test_frontend.py`

- [ ] Write failing tests that `/` serves the console and `/static/app.js` is available.
- [ ] Implement static file mounting and frontend interactions.
- [ ] Run `uv run --extra dev pytest tests/test_frontend.py -q`.

### Task 5: Functional Scripts and Docs

**Files:**
- Create: `scripts/create_sample_pdf.py`
- Create: `scripts/functional_check.py`
- Modify: `README.md`
- Create: `docs/verification/2026-06-17-queue-ui-verification.md`

- [ ] Add scripts to generate sample PDF and exercise health, single image, batch image, PDF, and job polling.
- [ ] Update README with new endpoints and UI usage.
- [ ] Run full tests, lint, service smoke checks, frontend browser check, and concurrency checks.

### Self-Review

- Scope covers the requested frontend, health check, batch images, PDF, queue, and functional testing.
- Queue is deliberately in-memory for the local LAN utility. Persistent jobs are out of scope for this iteration.
- No placeholders remain; each task has exact target files and verification commands.
