# 2026-06-17 Product Workbench Verification

Time: 2026-06-17 14:36:44 CST

Update: 2026-06-17 17:30 CST

## P1 Review Follow-up

OpenCode/k2p7 P1 review items were converted into pytest coverage and fixed:

- Batch upload limits now count the whole multipart request, not only each file.
- `PATCH /settings` rejects invalid ranges with `422`.
- PDF page OCR failures preserve successful pages, save partial outputs, and mark the job failed.
- Configurable CORS allowlist is wired through FastAPI middleware.
- Access logging writes request metadata to `logs/access.log` without OCR text or upload bodies.
- Retention cleanup deletes expired SQLite job rows plus output/upload files through `/operations/retention/cleanup`.

Frontend update: the no-build UI now uses a local shadcn/ui-inspired component layer: CSS tokens, cards, badges, buttons, tabs, alerts, inputs, and scroll areas. This keeps the current FastAPI static frontend while borrowing the open-source component vocabulary from shadcn/ui.

## Product Spec Audit

### Phase 1: Persistent Results and History

- SQLite job metadata: implemented with `data/paddleocr.sqlite3`.
- Output directory: implemented with `outputs/<job_id>/`.
- Automatic JSON/TXT/Markdown result saves for queued jobs: implemented.
- Restart-surviving history: implemented and covered by tests plus manual restart check.
- Frontend history list: implemented as `历史记录`.
- Download result files: implemented for JSON, TXT, and Markdown.
- Save original uploads setting: implemented. Default is `false`; original files are not saved unless enabled.

### Phase 2: Task Management

- Retry: implemented for failed jobs and canceled jobs when source payload is available in the running process. Restart-proof retry requires `save_uploads=true`.
- Cancel queued/running jobs: implemented. Running cancellation is cooperative and marks the job canceled when the current OCR unit returns.
- Delete job and outputs: implemented.
- Queue pause/resume: implemented.
- Upload size limits: implemented for single files and total batch multipart request size.
- MIME and actual image/PDF validation: implemented.
- Failed job/page error display: implemented through `error` fields, frontend alert text, and partial PDF output downloads.

### Phase 3: Result Review and Export

- Result detail page/panel: implemented.
- Copy recognized text: implemented.
- Download JSON/TXT/Markdown: implemented.
- PDF page navigation: implemented.
- CSV export: deferred. The current OCR shape is free text and boxes; CSV becomes useful with table extraction.

### Phase 4: Settings and Operations

- Settings page: implemented.
- Model warmup: implemented through `/operations/warmup`.
- OCR language setting: implemented, with OCR engine reload on change.
- PDF render scale setting: implemented.
- Retention policy setting: implemented with manual cleanup endpoint.
- Disk usage display: implemented in `/health` and UI.
- Version/model cache path: implemented in `/health` and UI.
- Health check extension: implemented.
- Running documentation: implemented in `README.md`.
- launchd/systemd/Docker docs: deferred as operational packaging, not needed for the local workbench MVP.

### Phase 5: Advanced Capability Evaluation

- PP-StructureV3/table extraction: deferred. It adds a separate document-structure pipeline and heavier dependency/runtime surface; persistence/export basics are now in place first.
- Markdown export: implemented for raw OCR results. Semantic document Markdown via PP-StructureV3 is deferred.
- Searchable PDF: deferred. OCRmyPDF-style output needs PDF reconstruction and quality controls beyond the current local queue.
- OCR box overlay: deferred. OCR boxes are preserved in JSON; image/PDF preview and coordinate mapping need a dedicated preview layer.
- Manual correction: deferred. The current model stores raw results; corrected text needs a separate saved artifact and edit UI.

## Automated Verification

```bash
uv run --extra dev pytest -q
# 34 passed

uv run ruff check .
# All checks passed!
```

## Functional Verification

```bash
uv run python scripts/create_sample_image.py
uv run python scripts/create_sample_pdf.py
uv run python scripts/functional_check.py
```

Latest output saved to `docs/verification/2026-06-17-p1-functional-check-output.json`.

Highlights:

- Single image recognized `PaddleOCR LAN Test`, `Invoice No: OCR-8866`, and `Amount: 123.45 USD`.
- Batch image job succeeded with 2 documents.
- PDF job succeeded with 2 pages.
- JSON/TXT/Markdown downloads returned saved output.
- Queue controls paused, canceled, retried, resumed, and completed a job.
- Settings validation returned `422` for invalid upload limit, PDF scale, and retention days.
- CORS preflight returned the configured allowed origin when `PADDLEOCR_CORS_ORIGINS` was set.
- Retention cleanup endpoint returned a cleanup summary.
- Deleted job returned `404` after delete.

## Manual Browser Verification

- Opened `http://127.0.0.1:8866/` with a real browser session.
- Uploaded a single image through the UI and saw `PaddleOCR LAN Test`.
- Uploaded two images through the batch UI and saw `image_batch · succeeded · 2/2`.
- Uploaded the sample PDF through the UI and saw `pdf · succeeded · 2/2`.
- Clicked the PDF history item and viewed page 1 and page 2 through page navigation.
- Used copy text and saw `文本已复制`.
- Fetched visible JSON/TXT/Markdown download links and received expected saved output.
- Deleted the selected PDF job through the UI; `/jobs` no longer included that job id.
- Used the shadcn-style UI controls for retention cleanup and saw the cleanup summary.
- Changed PDF render scale to `2.5` and retention days to `7`; `/health` reported the updated settings.
- Restarted Uvicorn; `/jobs/{id}` and TXT download still returned `200`.
- Set browser viewport to mobile width; layout check reported `horizontalOverflow: false`.

## Evidence Files

- `docs/verification/2026-06-17-functional-check-output.json`
- `docs/verification/2026-06-17-workbench-desktop.png`
- `docs/verification/2026-06-17-workbench-single-result.png`
- `docs/verification/2026-06-17-workbench-batch-pdf.png`
- `docs/verification/2026-06-17-workbench-pdf-detail.png`
- `docs/verification/2026-06-17-workbench-pdf-page2.png`
- `docs/verification/2026-06-17-browser-export-links.json`
- `docs/verification/2026-06-17-workbench-after-delete.png`
- `docs/verification/2026-06-17-jobs-after-browser-delete.json`
- `docs/verification/2026-06-17-health-after-settings.json`
- `docs/verification/2026-06-17-jobs-after-restart.json`
- `docs/verification/2026-06-17-download-after-restart.txt`
- `docs/verification/2026-06-17-workbench-after-restart.png`
- `docs/verification/2026-06-17-workbench-mobile.png`
- `docs/verification/2026-06-17-p1-targeted-tests.txt`
- `docs/verification/2026-06-17-shadcn-workbench-desktop.png`
- `docs/verification/2026-06-17-shadcn-workbench-mobile.png`
- `docs/verification/2026-06-17-p1-functional-check-output.json`
- `docs/verification/2026-06-17-playwright-shadcn-ui-flow.json`
- `docs/verification/2026-06-17-playwright-shadcn-delete-download.json`
- `docs/verification/2026-06-17-playwright-shadcn-desktop.png`
- `docs/verification/2026-06-17-playwright-shadcn-single-result.png`
- `docs/verification/2026-06-17-playwright-shadcn-pdf-detail.png`
- `docs/verification/2026-06-17-playwright-shadcn-after-delete.png`
- `docs/verification/2026-06-17-playwright-shadcn-mobile.png`
- `docs/verification/2026-06-17-p1-restart-check.txt`

## Remaining Risks

- Retry after process restart requires `PADDLEOCR_SAVE_UPLOADS=true`; this preserves the default privacy policy of not saving raw uploads.
- Running job cancellation is cooperative. It marks the job canceled after the current OCR unit returns.
- Retention cleanup is manual or scheduler-driven through the operation endpoint; the service does not run an internal cleanup scheduler yet.
- CSV/table export, searchable PDF, OCR overlay, PP-StructureV3, and manual correction are deferred Phase 5 work.
