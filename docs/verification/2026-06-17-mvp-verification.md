# MVP Verification - 2026-06-17

Environment:
- Host: macOS local machine
- Service bind: `0.0.0.0:8866`
- Python runtime selected by `uv`: Python 3.13
- PaddleOCR: 3.7.0
- PaddlePaddle: 3.3.1

Automated checks:

```bash
uv run --extra dev pytest -q
```

Result:

```text
7 passed in 0.53s
```

```bash
uv run ruff check .
```

Result:

```text
All checks passed!
```

Runtime checks:

```bash
curl -sS http://127.0.0.1:8866/health
```

Result before the first OCR request:

```json
{"status":"ok","ocr_loaded":false}
```

OCR sample:

```bash
uv run python scripts/create_sample_image.py
uv run python scripts/ocr_client.py samples/ocr_sample.png
```

Expected text in generated image:

```text
PaddleOCR LAN Test
Invoice No: OCR-8866
Amount: 123.45 USD
```

Recognized text:

```text
PaddleOCR LAN Test
Invoice No: OCR-8866
Amount: 123.45 USD
```

Observed elapsed time after model files were cached:

```text
4741 ms
```

Concurrency check:

```bash
uv run python scripts/bench_concurrency.py samples/ocr_sample.png --requests 8 --concurrency 2
```

Result:

```text
requests=8
concurrency=2
total_seconds=11.45
throughput_rps=0.70
latency_avg_ms=2853.02
latency_p50_ms=2798.56
latency_p95_ms=3082.68
status_counts={200: 8}
```

```bash
uv run python scripts/bench_concurrency.py samples/ocr_sample.png --requests 8 --concurrency 4
```

Result:

```text
requests=8
concurrency=4
total_seconds=14.20
throughput_rps=0.56
latency_avg_ms=6949.94
latency_p50_ms=7082.09
latency_p95_ms=7212.42
status_counts={200: 8}
```

Conclusion:
- The API surface works for the MVP: `/health` responds, `/ocr` accepts one image and returns recognized text, boxes, confidence, and elapsed time.
- The generated English sample was recognized exactly after sample image margin adjustment.
- In this local single-process run, `concurrency=2` performed better than `concurrency=4`; OCR inference is the bottleneck, so higher concurrency should be handled with care before adding more workers or a queue.
