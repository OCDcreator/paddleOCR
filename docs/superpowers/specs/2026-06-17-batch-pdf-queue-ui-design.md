# Batch PDF Queue UI Design

## Goal

Extend the existing PaddleOCR LAN service from single-image OCR into a usable local OCR console with health status, batch image OCR, PDF OCR, an in-memory queue, and functional verification.

## Scope

This iteration keeps deployment simple: one FastAPI process, no database, no Redis, no frontend build tool. Jobs live in memory and are lost when the process restarts. That is acceptable for a LAN utility where the first priority is local usability and simple operations.

## API

- `GET /health` returns service status, OCR model load state, queue status, and config.
- `POST /ocr` remains the synchronous single-image endpoint.
- `POST /jobs/images` accepts multiple image files and returns a queued job id.
- `POST /jobs/pdf` accepts one PDF and returns a queued job id.
- `GET /jobs/{job_id}` returns job status, progress, timestamps, errors, and OCR results.
- `GET /jobs` returns recent jobs.

## Queue Model

Use one in-process `asyncio.Queue` and a single worker by default. A job moves through `queued -> running -> succeeded` or `failed`. Results are normalized to document pages:

- image batch: one document per uploaded image, each with one page.
- PDF: one document for the uploaded PDF, one page per rendered PDF page.

The queue prevents concurrent OCR calls from overloading the local PaddleOCR model and makes progress visible to other devices.

## PDF Handling

Use `pypdfium2` to render each PDF page to a PNG image in memory, then pass the rendered image bytes through the existing OCR engine. The first version renders at scale 2.0 for readable text while keeping memory reasonable.

## Frontend

Serve a static no-build interface at `/`. It provides:

- health and queue status panel.
- single-image OCR upload.
- batch image upload.
- PDF upload.
- job list and job detail view with progress and text output.

The UI uses plain HTML/CSS/JavaScript to keep LAN deployment friction low.

## Testing

Unit and API tests cover queue lifecycle, batch image submission, PDF page rendering with a stub renderer, health payload shape, and static UI serving. Functional scripts generate sample images/PDFs, start the service, call APIs, and record observed OCR and queue results.
