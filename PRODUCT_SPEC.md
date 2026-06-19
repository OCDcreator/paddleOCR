# PaddleOCR LAN Service Product Spec

## 1. Product Positioning

PaddleOCR LAN Service is a private OCR hub for a local network. It turns one machine's local PaddleOCR capability into a browser console and HTTP API that phones, tablets, other computers, scripts, and automation tools can use.

The product should not stop at "upload one image and get text." Its useful shape is:

- a local OCR workbench for humans,
- a stable OCR API for other devices,
- a task processor for batch images and PDFs,
- a searchable record of past OCR work,
- an export pipeline for downstream use.

The first product principle is local-first privacy. Files and OCR results should stay on the user's machine unless the user explicitly sends them elsewhere.

## 2. Current State

Implemented:

- Single-image OCR API: `POST /ocr`
- Batch image job API: `POST /jobs/images`
- PDF job API: `POST /jobs/pdf`
- Job detail API: `GET /jobs/{job_id}`
- Recent jobs API: `GET /jobs`
- Health check API: `GET /health`
- Static frontend console: `GET /`
- In-process queue worker with SQLite-backed job history
- PDF page rendering through `pypdfium2`
- Saved JSON/TXT/Markdown outputs under `outputs/`
- Retry, cancel, delete, pause/resume queue controls
- Runtime settings page and API
- Upload size/type validation
- Optional upload preservation, disabled by default
- CORS allowlist config
- Request access logging without OCR text
- Manual retention cleanup endpoint
- shadcn/ui-inspired no-build component styling for the static frontend
- Functional smoke scripts and sample image/PDF generation

Known limitations:

- Original uploaded files are not saved unless explicitly enabled.
- Retry after process restart requires saved source payloads or still-available in-process source data.
- Running-job cancellation is cooperative and takes effect after the current OCR unit returns.
- Retention cleanup is exposed as an operation endpoint, not an automatic scheduler.
- No search/filter UI yet.
- No authentication or API token yet.
- No structured document understanding beyond normal OCR text/boxes.

## 3. Target Users and Use Cases

### Primary Users

- The owner of the LAN machine running the OCR service.
- Other trusted devices in the same LAN.
- Local scripts and automation workflows that need OCR.

### Core Use Cases

- Upload one screenshot or document photo and copy OCR text.
- Upload many images and process them as a batch.
- Upload a PDF and extract text page by page.
- Reopen a previous OCR result after a service restart.
- Export OCR result as text, JSON, Markdown, or CSV.
- Call OCR from another local app or device over HTTP.
- Monitor whether the OCR service and model are healthy.

## 4. Product Capability Framework

### 4.1 OCR Input

Required:

- Single image upload
- Multiple image upload
- PDF upload
- Image content validation
- PDF content validation
- Upload size limits

Later:

- Clipboard image paste in browser
- Screenshot upload from desktop helper
- Watched folder ingestion
- Zip archive ingestion
- URL-based image/PDF ingestion, disabled by default for safety

### 4.2 OCR Processing

Required:

- PaddleOCR PP-OCR pipeline
- Per-page/per-image progress
- Normalized result shape: text, confidence, box, page number, filename
- Lazy model loading
- Optional startup warmup

Later:

- OCR profiles: fast, balanced, accurate
- Language selection per job
- PDF render scale per job
- Image preprocessing: rotate, crop, grayscale, denoise, contrast
- Deskew and orientation correction
- Structured document parsing through PP-StructureV3
- Table extraction

### 4.3 Queue and Task Management

Required:

- Durable job IDs
- Status lifecycle: `queued`, `running`, `succeeded`, `failed`
- Job progress: total units and completed units
- Recent job list
- Job detail view

Next:

- Persistent queue state in SQLite
- Retry failed job
- Cancel queued/running job
- Delete job
- Pause/resume queue
- Configurable worker count
- Max queue length
- Job timeout

Later:

- Priority queue
- Webhook on completion
- Multi-process workers
- Redis/RQ/Celery only if single-process queue becomes insufficient

### 4.4 History and Persistence

Required next:

- SQLite database for job metadata
- `outputs/` directory for OCR result files
- Save OCR result as JSON
- Save OCR result as TXT
- Save OCR result as Markdown
- Keep result records across restart

Policy decisions:

- Default should save OCR results.
- Default should not save original uploaded files.
- Saving original files should be an explicit setting.
- Temporary rendered PDF page images should be deleted after processing.

Later:

- Search history by filename, recognized text, date, status, source device
- File hash deduplication
- Retention policy: manual, days, max disk usage
- Export all selected tasks

### 4.5 Result Review and Export

Required:

- Copy recognized text
- Download JSON
- Download TXT
- Download Markdown
- View per-page results for PDFs

Later:

- CSV/Excel export for table-like results
- Side-by-side image/PDF preview and text
- Highlight OCR boxes over preview image
- Manual text correction
- Save corrected text separately from raw OCR
- Searchable PDF generation

### 4.6 Frontend Console

Required:

- Health panel
- Single image upload
- Batch image upload
- PDF upload
- Job list
- Job detail
- Copy/download result

Next:

- History page
- Settings page
- Result detail page with per-page navigation
- Clear visual distinction between queued/running/succeeded/failed
- Error display for failed pages/jobs
- Mobile-friendly layout for phones on LAN

Later:

- Preview uploaded image/PDF pages
- OCR box overlay
- Drag-and-drop upload
- Paste image from clipboard
- Batch operation toolbar

### 4.7 API and Integration

Required:

- REST endpoints
- OpenAPI docs from FastAPI
- Stable response schema
- Functional test client

Next:

- API token, optional and disabled by default
- Client examples: curl, Python, JavaScript
- Webhook callback on job completion
- Download endpoints for saved outputs

Later:

- SDK wrapper for Python
- CLI command for remote OCR
- Integration examples for Obsidian, automation scripts, and local agents

### 4.8 Security and Privacy

Required:

- LAN-first default
- No external upload by default
- Validate MIME type and actual content
- Upload size limits
- Clear setting for whether original files are saved

Next:

- Optional API token
- CORS config
- Allowed hosts/origins config
- Basic request logging without leaking OCR text by default

Later:

- Per-device token labels
- Audit log
- Rate limiting

### 4.9 Operations

Required:

- One-command local startup
- `.env` config
- Health endpoint
- Functional smoke test script

Next:

- Persistent logs
- Disk usage summary
- Queue metrics in `/health`
- Model cache path display
- Version info endpoint

Later:

- Dockerfile
- macOS launchd plist
- systemd service
- Automatic startup guide

## 5. Recommended Architecture

### Near-Term Architecture

Keep a single FastAPI application:

- API routes and static frontend served by FastAPI.
- PaddleOCR engine loaded lazily.
- In-process queue worker.
- SQLite for metadata.
- Local filesystem for outputs and optional uploads.

This is the right next step because it preserves the current simple LAN deployment while adding the most important product capability: persistent history and result files.

### Medium-Term Architecture

Split into internal modules:

- `storage.py`: filesystem paths, saved outputs, optional uploaded files.
- `database.py`: SQLite connection and migrations.
- `repositories.py`: job/result persistence.
- `jobs.py`: queue and worker lifecycle.
- `processors.py`: image/PDF OCR processing.
- `exports.py`: JSON/TXT/Markdown/CSV generation.
- `settings.py` or current `config.py`: environment-driven config.

Do not introduce Redis, Celery, a separate frontend build, or object storage until the simple local architecture clearly fails.

## 6. Technology Stack

### Backend

- FastAPI: HTTP API, static serving, OpenAPI docs.
- Uvicorn: ASGI server.
- PaddleOCR: OCR model and inference.
- PaddlePaddle: PaddleOCR runtime.
- pypdfium2: PDF page rendering to images.
- Pillow: image validation, sample image/PDF generation.
- SQLite: persistent local metadata and history.
- Local filesystem: result files and optional source file storage.
- pytest + httpx: automated API and behavior tests.
- ruff: linting.

### Frontend

Current and near-term:

- Plain HTML/CSS/JavaScript.
- No build step.
- Fetch API for backend calls.

Possible later:

- React/Vite or Vue/Vite only when UI complexity exceeds what plain JS can reasonably maintain.

### Queue

Current and near-term:

- `asyncio.Queue` plus one worker.
- SQLite persistence for job metadata.

Possible later:

- Multiple in-process workers.
- Process pool for OCR isolation.
- Redis/RQ/Celery only for multi-machine or heavier workloads.

## 7. Reference Projects and What to Learn

### shadcn/ui

Repository: https://github.com/shadcn-ui/ui

Use it as UI reference for:

- accessible component primitives
- button, badge, card, tabs, alert, and input visual language
- source-owned component philosophy

This project keeps a no-build static frontend for now, so shadcn/ui is applied as a design system reference and local CSS/HTML component layer rather than a React/Vite dependency.

### PaddleOCR

Repository: https://github.com/PaddlePaddle/PaddleOCR

Use it as the source of truth for:

- PP-OCR pipeline usage
- PaddleOCR model options
- PP-StructureV3 document parsing direction
- Serving and deployment concepts
- High-performance inference options

### PaddleOCR PP-OCR Documentation

Docs: https://paddlepaddle.github.io/PaddleOCR/latest/en/version3.x/pipeline_usage/OCR.html

Use it for:

- current Python API behavior
- OCR pipeline parameters
- output shape expectations

### Umi-OCR

Repository: https://github.com/hiroi-sora/Umi-OCR

Use it as product reference for:

- offline OCR workbench shape
- batch OCR UX
- screenshot/image/PDF workflow ideas
- local-first OCR product expectations

Do not copy its architecture blindly; this project is a LAN service plus API, not a desktop-only app.

### Stirling PDF

Repository: https://github.com/Stirling-Tools/Stirling-PDF

Use it as reference for:

- self-hosted document tool UI
- private local deployment
- PDF operation organization
- browser-first tool workflows

### OCRmyPDF

Docs: https://ocrmypdf.readthedocs.io/en/latest/

Use it as reference for:

- searchable PDF generation
- sidecar text output
- deskew/rotate/clean PDF processing concepts
- PDF OCR pipeline maturity

Do not immediately reimplement OCRmyPDF. Treat searchable PDF as a later capability.

## 8. Roadmap

### Phase 1: Persistent Results and History

Goal: OCR results survive restart and can be reviewed later.

Features:

- SQLite database
- Result output directory
- Save JSON/TXT/Markdown for every queued job
- History page in frontend
- Job delete
- Download result files
- Config: save original uploads true/false

Success criteria:

- Submit batch/PDF job.
- Restart service.
- History still shows job.
- Result files can be downloaded.
- Original files are not saved unless enabled.

### Phase 2: Task Management

Goal: Make queue operations controllable.

Features:

- Retry failed job
- Cancel queued job
- Delete job and saved outputs
- Queue pause/resume
- Better progress and error display
- Upload limits

Success criteria:

- Failed PDF page records useful error.
- User can retry failed job.
- User can delete job and outputs.

### Phase 3: Result Review and Export

Goal: Make results useful after OCR.

Features:

- Result detail page
- Copy text
- Download JSON/TXT/Markdown
- Per-page PDF navigation
- CSV export for simple table-like output

Success criteria:

- User can finish common OCR workflow from browser without opening terminal.

### Phase 4: Settings and Operations

Goal: Make it comfortable to run as a local service.

Features:

- Settings page
- Model warmup toggle
- OCR language setting
- PDF scale setting
- Retention policy
- Disk usage display
- Version endpoint
- launchd/systemd/Docker docs

Success criteria:

- User can configure service without editing code.
- Service can run continuously on a LAN machine.

### Phase 5: Advanced Document Intelligence

Goal: Move beyond raw OCR text.

Features:

- PP-StructureV3 evaluation
- Table extraction
- Markdown document export
- Searchable PDF generation
- OCR box overlay
- Manual correction workflow

Success criteria:

- Structured documents become usable in downstream note-taking, search, and LLM/RAG workflows.

## 9. Non-Goals for Now

Do not build these yet:

- Multi-user account system
- Cloud sync
- Public internet exposure
- Payment or quota system
- Complex distributed queue
- Full desktop app
- Full React/Vue rewrite
- Searchable PDF generation before persistence/export basics
- Training or fine-tuning PaddleOCR models

## 10. Immediate Next Implementation Recommendation

Implement Phase 1 first:

1. Add SQLite database for job metadata.
2. Add output directory management.
3. Persist queued job status and results.
4. Save result files as JSON/TXT/Markdown.
5. Add frontend history page/list.
6. Add download endpoints.
7. Add tests proving results survive service restart.

This is the right next step because it turns the current temporary OCR console into a real local product. It also creates the foundation for delete, retry, export, search, settings, and retention policies.
