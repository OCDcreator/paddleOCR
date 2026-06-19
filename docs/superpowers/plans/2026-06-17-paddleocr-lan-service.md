# PaddleOCR LAN Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a LAN-accessible FastAPI service that exposes local PaddleOCR for single-image OCR through `POST /ocr` and reports readiness through `GET /health`.

**Architecture:** The FastAPI app accepts one uploaded image, validates that it is an image, passes image bytes to a lazily initialized OCR engine, and returns normalized OCR items plus merged text and elapsed time. The PaddleOCR-specific parsing is isolated in `ocr_engine.py` so API tests can use a fake engine and real OCR can be verified separately.

**Tech Stack:** Python 3.11-3.13, FastAPI, Uvicorn, Pillow, PaddleOCR, pytest, httpx.

---

### Task 1: API Contract Tests

**Files:**
- Create: `tests/test_health.py`
- Create: `tests/test_ocr_api.py`
- Create: `tests/test_ocr_engine.py`
- Create: `pyproject.toml`

- [ ] **Step 1: Write failing tests for health, upload response, upload validation, and result parsing.**

- [ ] **Step 2: Run `uv run --extra dev pytest -q` and verify tests fail because `paddleocr_service` does not exist.**

### Task 2: Service Implementation

**Files:**
- Create: `src/paddleocr_service/__init__.py`
- Create: `src/paddleocr_service/config.py`
- Create: `src/paddleocr_service/schemas.py`
- Create: `src/paddleocr_service/ocr_engine.py`
- Create: `src/paddleocr_service/main.py`

- [ ] **Step 1: Implement settings, response schemas, PaddleOCR result parsing, FastAPI app factory, and CLI run entrypoint.**

- [ ] **Step 2: Run `uv run --extra dev pytest -q` and verify tests pass.**

### Task 3: Docs and Manual Verification

**Files:**
- Create: `README.md`
- Create: `.env.example`
- Create: `scripts/create_sample_image.py`
- Create: `scripts/ocr_client.py`
- Create: `scripts/bench_concurrency.py`

- [ ] **Step 1: Document install, startup, LAN access, curl usage, and next-step roadmap.**

- [ ] **Step 2: Add sample image generation, client call, and concurrency benchmark scripts.**

- [ ] **Step 3: Start the service on `0.0.0.0:8866`, call `/health`, call `/ocr` with generated image, and run a small concurrency benchmark.**

### Self-Review

- Requirement coverage: `POST /ocr`, `GET /health`, `0.0.0.0:8866`, single-image scope, OCR accuracy check, and concurrency check are covered.
- Placeholder scan: no TBD/TODO placeholders.
- Type consistency: `OCRItem` dictionaries consistently use `text`, `confidence`, and `box`; API responses use `text`, `items`, and `elapsed_ms`.
