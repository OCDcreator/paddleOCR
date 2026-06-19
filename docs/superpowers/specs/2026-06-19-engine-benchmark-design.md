# OCR Engine Benchmark Design

## Goal

Produce evidence — not opinion — for whether PaddleOCR should remain the default OCR backend on Mac, or whether a faster engine (RapidOCR / a lighter PaddleOCR model tier) should replace it.

Build a standalone benchmark that runs competing OCR configurations on the same batch of test images and reports **speed plus accuracy**, so the framework choice rests on measured data from this machine.

## Background

Current state (from `docs/verification/2026-06-17-mvp-verification.md` and `src/paddleocr_service/ocr_engine.py`):

- The service calls `PaddleOCR(lang=..., use_textline_orientation=...)` with **no device or model-tier argument**, so on Mac PaddlePaddle runs on CPU with the default high-accuracy model tier.
- Measured single-image latency after model cache: ~4.7 s; concurrency=2 → 2.85 s avg, concurrency=4 → 6.95 s avg (slower). CPU inference is the bottleneck.
- Two stacked factors cause the slowness: device = CPU, and model = server high-accuracy tier. Both are tunable without leaving PaddleOCR.

This benchmark isolates each factor and adds an entirely different runtime (RapidOCR / ONNX) as a candidate.

## Scope

In scope:
- A cross-platform (macOS + Windows) benchmark script and a fixture generator.
- Comparing speed and accuracy across a defined set of engine configurations.
- Writing a machine-readable and a human-readable report for decision-making.

Out of scope (deliberate, YAGNI):
- Modifying `ocr_engine.py`, the service, or any runtime config. The benchmark is read-only; no pluggable-backend plumbing is introduced yet.
- Adding an `.env` engine switch. That decision comes after the data, in a separate spec.
- PDF OCR benchmarking. PDF performance is dominated by the renderer (`pypdfium2`) plus per-page image OCR; the image benchmark already captures the OCR-engine cost.
- Cloud OCR engines. Violates the local-first product principle (`PRODUCT_SPEC.md`).

## Contenders

Each contender is a separate configuration to be measured:

| Id | Engine | Configuration |
|----|--------|---------------|
| `paddleocr-default` | PaddleOCR | Current behavior: default model tier, `lang=ch`, `use_textline_orientation=true`. The baseline. |
| `paddleocr-mobile` | PaddleOCR | Lightweight model tier, configured via PaddleOCR 3.x's documented smaller detection/recognition model parameters. If the installed version exposes no clean lightweight switch, this contender degrades to `unavailable` (covered by the failure rule below) rather than guessing args. The zero-cost optimization. |
| `rapidocr` | RapidOCR (ONNX Runtime) | Default Chinese model, CPU. The primary candidate. |

A contender that fails to install or crashes is reported as `unavailable` and does not abort the run. The benchmark measures whichever contenders are present.

## Fixtures (test images + ground truth)

A generator module produces a set of synthetic images, each paired with its exact expected text (ground truth), because the text is drawn programmatically with Pillow.

Fixture categories:

| Category | Content | Exercises |
|----------|---------|-----------|
| `english-single` | One line of English + digits (`Invoice No: OCR-8866`) | Baseline recognition |
| `chinese-multiline` | Several short Chinese lines | Chinese accuracy |
| `mixed-zh-en` | Mixed Chinese and English/digits (`金额 123.45 USD`) | Mixed-script handling |
| `dense-multiline` | 10+ lines | Throughput / sustained load |
| `large-resolution` | High-resolution canvas | Scale robustness |

Outputs land in `samples/benchmark/` (gitignored; recreated on demand). Ground truth is written to `samples/benchmark/ground_truth.json` keyed by image filename.

### Cross-platform font handling

Chinese text requires a CJK-capable TrueType font, whose path differs between macOS (PingFang / STHeiti under `/System/Library/Fonts/`) and Windows (Microsoft YaHei under `C:\Windows\Fonts\`). The fixture generator:

1. Probes a small ordered list of candidate font paths per category.
2. Uses the first font that exists for CJK categories.
3. If no CJK font is found, the CJK/mixed categories are **skipped with an explicit note** rather than emitting tofu boxes, and the English/dense/large categories still run. The report records which categories ran on which platform.

This keeps the benchmark runnable on both platforms without shipping a font binary.

## Process Isolation

Each contender runs in its **own subprocess** and, by convention, its own `uv` venv. Rationale:

- PaddlePaddle and onnxruntime can have conflicting native dependencies; isolating them avoids polluting the project's main `.venv` (which the service depends on).
- A contender that is not installed on a given machine is simply `unavailable` rather than a crash.
- The same machine runs all present contenders under identical conditions, giving a fair comparison. Splitting contenders across machines is supported (each subprocess is self-contained) but results from different hardware are not directly comparable and the report records the host.

Communication protocol between the driver and a contender subprocess:

- Driver spawns contender process, passing config (model tier, etc.) as CLI args or a small JSON on stdin.
- For each image: driver writes the contender's result line (JSON: `{"image": "...", "text": "...", "elapsed_ms": N, "error": null}`) to the contender's stdout; driver reads it.
- Image bytes/files are passed by path (fixtures live on disk), not over the pipe, to keep the protocol simple and avoid base64 overhead.

A thin adapter shim per engine normalizes each engine's native output into the common `{text, items}` shape, mirroring the existing `parse_paddleocr_result` in `ocr_engine.py` so accuracy comparison is apples-to-apples.

## Measurement Protocol

For each contender × image pair:

1. **Warmup**: run the image through the engine 1–2 times; discard timings. Covers lazy model load and first-call compile.
2. **Measured runs**: run `N` times (default 5, configurable). Record wall-clock per run.
3. **Latency**: median of the measured runs for that image (robust to outliers).
4. **Accuracy**: from one canonical run (the first measured run), compare recognized text to ground truth.

Accuracy metrics:

- **Character accuracy** = `1 - (edit_distance / len(ground_truth))`, computed on the normalized concatenated text.
- **Edit distance** (Levenshtein) raw count, for transparency.
- **Exact-line match rate** = fraction of ground-truth lines that appear verbatim in the output (rough structural metric).

Normalization before comparison: collapse whitespace, strip, ignore case. This avoids penalizing trivial spacing differences; the note is recorded in the report.

Reported aggregates per contender:

- Median latency per image category, and overall.
- Throughput estimate = `1 / median_latency` for the single-image case (note: not the same as the queue's concurrency throughput, recorded as a caveat).
- Mean character accuracy and mean edit distance per category and overall.
- Mean exact-line match rate.

## Outputs

1. **Terminal**: a summary table (contender rows × metrics columns) printed at the end of the run, plus per-category breakdown.
2. **Machine-readable**: `docs/verification/<date>-engine-benchmark.json` — full per-image, per-run data plus aggregates, for later re-analysis or plotting.
3. **Human-readable**: `docs/verification/<date>-engine-benchmark.md` — the summary tables with a short "how to read this" note and the host/platform/Python/versions recorded. This is the artifact a human reads to decide.

Both verification files follow the existing `docs/verification/` naming convention.

## File Layout

```
scripts/
  benchmark_fixtures.py     # generates samples/benchmark/* + ground_truth.json
  benchmark_engines.py      # driver: orchestrate contenders, time, score, report
  benchmark_adapters/       # one adapter shim per engine, run as a subprocess
    paddleocr_adapter.py    # reused for paddleocr-default and paddleocr-mobile (config via arg)
    rapidocr_adapter.py
```

Adapter shims are intentionally minimal: import the engine, load the model once, loop reading image paths from stdin and writing result JSON to stdout. The driver picks the right shim per contender and passes configuration (e.g. model tier) as an argument, so the PaddleOCR shim serves both `paddleocr-default` and `paddleocr-mobile`.

## Non-Goals / Decisions Deferred

- Choosing the winning engine. That happens after reading the report, in a follow-up.
- Any change to the running service. This benchmark does not touch the service code path.
- GPU/MPS acceleration. Out of scope for this round; CPU-only is what the service currently uses, so CPU is the fair baseline. A future spec may revisit if a contender's ONNX/CoreML path looks promising.
- Multi-image concurrency tuning. The existing concurrency benchmark (`scripts/bench_concurrency.py`) already covers that for the current engine; this benchmark focuses on per-image latency and accuracy.

## Success Criteria

- Running `benchmark_engines.py` on macOS and on Windows produces a report without manual editing.
- At least two contenders are measurable on the primary Mac machine.
- The report answers, with numbers: "Is the current PaddleOCR default the right speed/accuracy tradeoff, or does a lighter tier or RapidOCR win?"
- No changes to the service or its dependencies; the project remains runnable exactly as before.
