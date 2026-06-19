# OCR Engine Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a cross-platform benchmark that measures speed and accuracy of PaddleOCR (default + lightweight tier) and RapidOCR on synthetic test images with known ground truth, so the OCR backend choice rests on measured data.

**Architecture:** Two script modules plus per-engine adapter subprocesses. `benchmark_fixtures.py` generates test images + a `ground_truth.json`. `benchmark_engines.py` is the driver: for each contender it spawns that engine's adapter as a subprocess, streams image paths over stdin, collects timed JSON results over stdout, then scores accuracy against ground truth and prints + writes reports. Each engine lives in its own `uv` venv to avoid dependency conflicts; a missing engine degrades to `unavailable` instead of crashing.

**Tech Stack:** Python 3.11–3.13, Pillow (already a dep), `uv` for venvs, stdlib `subprocess`/`json`/`statistics`/`difflib` for the driver. Adapters import their respective engines (paddleocr / rapidocr-onnxruntime). pytest tests load scripts via `importlib.util` (matches existing `tests/test_sample_scripts.py` pattern).

---

## File Structure

```
scripts/
  benchmark_fixtures.py            # generate samples/benchmark/* + ground_truth.json
  benchmark_engines.py             # driver: orchestrate, time, score, report
  benchmark_adapters/
    __init__.py                    # empty, makes dir importable
    paddleocr_adapter.py           # one shim, serves default + mobile via --tier arg
    rapidocr_adapter.py            # RapidOCR shim
tests/
  test_benchmark_fixtures.py       # fixture generator tests
  test_benchmark_engines.py        # driver scoring/protocol tests (uses a fake adapter)
```

Each file has one responsibility: fixtures = make images + truth; adapters = run one engine and emit results; driver = orchestration + scoring + reporting. The driver never imports an OCR engine directly — that isolation is what makes engine venvs independent and fair.

Report outputs (generated at run time, not source): `docs/verification/<date>-engine-benchmark.{json,md}` and `samples/benchmark/ground_truth.json` (samples/ is gitignored).

---

## Conventions for this plan

- Project uses `from __future__ import annotations` at the top of every module — every new `.py` file starts with it.
- Scripts use argparse with a `main()` entry point, matching `scripts/bench_concurrency.py` / `scripts/ocr_client.py`.
- Tests load scripts via `importlib.util.spec_from_file_location` because scripts are not in a package — copy the pattern from `tests/test_sample_scripts.py`.
- Line length 100, ruff rules E/F/I/UP/B (already configured in `pyproject.toml`).
- Adapter protocol: the driver writes one **request line** to the adapter's stdin (JSON: `{"image": "<abs path>"}`), the adapter writes one **result line** to stdout (JSON: `{"image": "...", "text": "...", "items": [...], "elapsed_ms": N, "error": null}`). A blank line / EOF ends the stream.
- All adapters normalize their engine's native output into the service's existing item shape `{"text": str, "confidence": float, "box": [[x,y],...]}` so accuracy scoring is apples-to-apples. The driver extracts the joined `text` from `items` for scoring.

---

## Task 1: Fixture generator — ground truth structure and font probe

**Files:**
- Create: `scripts/benchmark_fixtures.py`
- Create: `tests/test_benchmark_fixtures.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_benchmark_fixtures.py`:

```python
from __future__ import annotations

import importlib.util
from pathlib import Path


def load_fixtures_module():
    script_path = Path(__file__).parents[1] / "scripts" / "benchmark_fixtures.py"
    spec = importlib.util.spec_from_file_location("benchmark_fixtures", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_font_returns_path_or_none() -> None:
    fixtures = load_fixtures_module()
    # Returns a Path when a CJK font is found, or None when none is available.
    result = fixtures.probe_cjk_font()
    assert result is None or isinstance(result, Path)


def test_ground_truth_entries_have_required_keys(tmp_path, monkeypatch) -> None:
    fixtures = load_fixtures_module()
    monkeypatch.chdir(tmp_path)
    fixtures.generate_all(out_dir=Path("samples/benchmark"))
    truth_path = Path("samples/benchmark/ground_truth.json")
    assert truth_path.exists()
    import json

    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    assert isinstance(truth, list) and len(truth) > 0
    for entry in truth:
        assert {"image", "category", "text", "needs_cjk"} <= set(entry.keys())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_benchmark_fixtures.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'benchmark_fixtures'` (file does not exist yet).

- [ ] **Step 3: Write minimal implementation**

Create `scripts/benchmark_fixtures.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# CJK font candidates per platform, in preference order.
CJK_FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    # Windows
    "C:/Windows/Fonts/msyh.ttc",      # Microsoft YaHei
    "C:/Windows/Fonts/simhei.ttf",    # SimHei
    # Linux
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def probe_cjk_font() -> Path | None:
    """Return the first available CJK font path, or None if none found."""
    for candidate in CJK_FONT_CANDIDATES:
        if Path(candidate).exists():
            return Path(candidate)
    return None


# Each entry: (category, text, needs_cjk, width, height, font_size)
FIXTURE_SPECS = [
    ("english-single", "Invoice No: OCR-8866\nAmount: 123.45 USD", False, 600, 160, 32),
    ("chinese-multiline", "你好世界\n中文识别测试\n局域网 OCR", True, 600, 240, 36),
    ("mixed-zh-en", "金额 123.45 USD\n日期 2026-06-19", True, 600, 160, 32),
    ("dense-multiline", "\n".join(f"Line {i}: value {i}" for i in range(12)), False, 700, 480, 26),
    ("large-resolution", "Big Canvas OCR Test\nResolution stress", False, 1600, 900, 48),
]


def _draw_image(text: str, width: int, height: int, font_size: int, font_path: Path | None) -> bytes:
    image = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype(str(font_path), font_size) if font_path else ImageFont.load_default()
    except OSError:
        font = ImageFont.load_default()
    # Draw each line stacked from a top margin.
    y = 20
    for line in text.split("\n"):
        draw.text((20, y), line, fill="black", font=font)
        y += font_size + 12
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def generate_all(out_dir: Path) -> list[dict]:
    """Generate all fixture images + ground_truth.json. Returns the truth list.

    CJK-requiring categories are skipped (and recorded) when no CJK font is found,
    so the benchmark still runs on a host without CJK fonts.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cjk_font = probe_cjk_font()
    truth: list[dict] = []
    for category, text, needs_cjk, width, height, font_size in FIXTURE_SPECS:
        if needs_cjk and cjk_font is None:
            continue  # skip CJK category on hosts without a CJK font
        font_path = cjk_font if needs_cjk else None
        filename = f"{category}.png"
        (out_dir / filename).write_bytes(_draw_image(text, width, height, font_size, font_path))
        truth.append(
            {"image": filename, "category": category, "text": text, "needs_cjk": needs_cjk}
        )
    (out_dir / "ground_truth.json").write_text(
        json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return truth


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate OCR benchmark fixtures.")
    parser.add_argument("--out", type=Path, default=Path("samples/benchmark"))
    args = parser.parse_args()
    truth = generate_all(args.out)
    cjk = probe_cjk_font() is not None
    print(f"wrote {len(truth)} fixtures to {args.out}")
    print(f"cjk_font_available={cjk}")
    if not cjk:
        print("note: CJK categories skipped because no CJK font was found")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_benchmark_fixtures.py -v`
Expected: PASS (3 tests). On a host without a CJK font, CJK categories are skipped but `truth` still contains the non-CJK entries, so `len(truth) > 0` holds.

- [ ] **Step 5: Run lint**

Run: `uv run ruff check scripts/benchmark_fixtures.py tests/test_benchmark_fixtures.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add scripts/benchmark_fixtures.py tests/test_benchmark_fixtures.py
git commit -m "Add benchmark fixture generator with cross-platform CJK font probe"
```

---

## Task 2: Adapter protocol module + PaddleOCR adapter

**Files:**
- Create: `scripts/benchmark_adapters/__init__.py`
- Create: `scripts/benchmark_adapters/paddleocr_adapter.py`

- [ ] **Step 1: Create the package marker**

Create `scripts/benchmark_adapters/__init__.py` with only the future-annotations header (the directory must be importable later if needed, but adapters run as standalone scripts):

```python
from __future__ import annotations
```

- [ ] **Step 2: Write the PaddleOCR adapter**

Create `scripts/benchmark_adapters/paddleocr_adapter.py`:

```python
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


def normalize(raw: Any) -> list[dict]:
    """Normalize PaddleOCR output into the service's {text, confidence, box} shape.

    Mirrors paddleocr_service.ocr_engine.parse_paddleocr_result so adapter output
    is directly comparable to the running service.
    """
    if not raw:
        return []
    candidates = raw[0] if isinstance(raw, list) and len(raw) == 1 and isinstance(raw[0], list) else raw
    items: list[dict] = []
    for candidate in candidates:
        if isinstance(candidate, dict):
            texts = candidate.get("rec_texts")
            scores = candidate.get("rec_scores")
            if texts is not None and scores is not None:
                boxes = candidate.get("rec_polys") or candidate.get("dt_polys") or candidate.get("rec_boxes") or []
                for text, score, box in zip(texts, scores, boxes, strict=False):
                    items.append({"text": str(text), "confidence": float(score), "box": _box(box)})
                continue
            text = candidate.get("text") or candidate.get("rec_text")
            score = candidate.get("confidence") or candidate.get("score")
            box = candidate.get("box") or candidate.get("points") or candidate.get("dt_polys")
            if text is not None and score is not None and box is not None:
                items.append({"text": str(text), "confidence": float(score), "box": _box(box)})
            continue
        if isinstance(candidate, (list, tuple)) and len(candidate) >= 2:
            box = _box(candidate[0])
            tas = candidate[1]
            if isinstance(tas, (list, tuple)) and len(tas) >= 2:
                items.append({"text": str(tas[0]), "confidence": float(tas[1]), "box": box})
    return items


def _box(box: Any) -> list[list[float]]:
    out: list[list[float]] = []
    for point in box:
        if hasattr(point, "tolist"):
            point = point.tolist()
        out.append([float(point[0]), float(point[1])])
    return out


def build_engine(lang: str, tier: str) -> Any:
    """Build the PaddleOCR engine for the given tier.

    tier='default' mirrors the running service (no extra model args).
    tier='mobile' requests the lightweight detection model via PaddleOCR 3.x's
    documented det model name; if the installed version rejects it, main() catches
    the error and reports it so the driver marks the contender unavailable.
    """
    from paddleocr import PaddleOCR

    kwargs: dict[str, Any] = {"lang": lang, "use_textline_orientation": True}
    if tier == "mobile":
        # PaddleOCR 3.7.0 ships no PP-OCRv5 mobile detector (only server), so the
        # newest available lightweight detection model is PP-OCRv4_mobile_det.
        kwargs["text_detection_model_name"] = "PP-OCRv4_mobile_det"
    return PaddleOCR(**kwargs)


def run_loop(engine: Any) -> None:
    """Read image paths from stdin (one JSON request per line), write results to stdout."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        image_path = Path(request["image"])
        result = {"image": str(image_path), "text": "", "items": [], "elapsed_ms": 0, "error": None}
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp.write(image_path.read_bytes())
                tmp_path = Path(tmp.name)
            try:
                import time

                start = time.perf_counter()
                raw = engine.predict(str(tmp_path))
                result["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
                items = normalize(raw)
                result["items"] = items
                result["text"] = "\n".join(i["text"] for i in items)
            finally:
                tmp_path.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001 - report any failure, do not crash the stream
            result["error"] = f"{type(exc).__name__}: {exc}"
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description="PaddleOCR benchmark adapter subprocess.")
    parser.add_argument("--tier", choices=["default", "mobile"], default="default")
    parser.add_argument("--lang", default="ch")
    args = parser.parse_args()
    try:
        engine = build_engine(args.lang, args.tier)
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(json.dumps({"fatal": f"{type(exc).__name__}: {exc}"}) + "\n")
        sys.stdout.flush()
        return
    run_loop(engine)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Lint check (no test — adapter needs the real engine)**

Run: `uv run ruff check scripts/benchmark_adapters/`
Expected: `All checks passed!`

Note: The adapter is exercised end-to-end in Task 4's driver test via a *fake* adapter, so no unit test imports the real PaddleOCR here. This keeps the test suite from requiring the heavy engine dependency.

- [ ] **Step 4: Commit**

```bash
git add scripts/benchmark_adapters/__init__.py scripts/benchmark_adapters/paddleocr_adapter.py
git commit -m "Add PaddleOCR benchmark adapter with default and mobile tiers"
```

---

## Task 3: RapidOCR adapter

**Files:**
- Create: `scripts/benchmark_adapters/rapidocr_adapter.py`

- [ ] **Step 1: Write the RapidOCR adapter**

Create `scripts/benchmark_adapters/rapidocr_adapter.py`. Its `normalize` reuses the same shape; the engine call differs (RapidOCR returns `(boxes, text, scores)` tuples or a result object depending on version, so we handle both):

```python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _box(box: Any) -> list[list[float]]:
    out: list[list[float]] = []
    for point in box:
        out.append([float(point[0]), float(point[1])])
    return out


def normalize(result: Any) -> list[dict]:
    """Normalize RapidOCR output into {text, confidence, box}.

    RapidOCR (rapidocr_onnxruntime) returns a 2-tuple: (lines, elapse), where
    `lines` is a list of [box, text, score] entries and `elapse` is a timing
    list. Newer unified `rapidocr` returns a Result object with .txts/.scores/
    .boxes. Handle all shapes.
    """
    items: list[dict] = []
    if result is None:
        return items
    # Unpack the (lines, elapse) tuple shape from rapidocr_onnxruntime.
    if isinstance(result, tuple) and len(result) >= 1 and isinstance(result[0], list):
        result = result[0]
    txts = getattr(result, "txts", None)
    scores = getattr(result, "scores", None)
    boxes = getattr(result, "boxes", None)
    if txts is not None and scores is not None and boxes is not None:
        for text, score, box in zip(txts, scores, boxes, strict=False):
            items.append({"text": str(text), "confidence": float(score), "box": _box(box)})
        return items
    if isinstance(result, (list, tuple)):
        for entry in result:
            if isinstance(entry, (list, tuple)) and len(entry) >= 3:
                box, text, score = entry[0], entry[1], entry[2]
                items.append({"text": str(text), "confidence": float(score), "box": _box(box)})
    return items


def build_engine() -> Any:
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def run_loop(engine: Any) -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        image_path = Path(request["image"])
        result = {"image": str(image_path), "text": "", "items": [], "elapsed_ms": 0, "error": None}
        try:
            import time

            start = time.perf_counter()
            raw = engine(str(image_path))
            result["elapsed_ms"] = int((time.perf_counter() - start) * 1000)
            items = normalize(raw)
            result["items"] = items
            result["text"] = "\n".join(i["text"] for i in items)
        except Exception as exc:  # noqa: BLE001
            result["error"] = f"{type(exc).__name__}: {exc}"
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def main() -> None:
    argparse.ArgumentParser(description="RapidOCR benchmark adapter subprocess.").parse_args()
    try:
        engine = build_engine()
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(json.dumps({"fatal": f"{type(exc).__name__}: {exc}"}) + "\n")
        sys.stdout.flush()
        return
    run_loop(engine)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Lint check**

Run: `uv run ruff check scripts/benchmark_adapters/rapidocr_adapter.py`
Expected: `All checks passed!`

- [ ] **Step 3: Commit**

```bash
git add scripts/benchmark_adapters/rapidocr_adapter.py
git commit -m "Add RapidOCR benchmark adapter"
```

---

## Task 4: Driver — scoring helpers (accuracy + latency) with tests

**Files:**
- Create: `scripts/benchmark_engines.py`
- Create: `tests/test_benchmark_engines.py`

The driver is one module but built in three test-driven slices: scoring helpers (Task 4), adapter subprocess protocol (Task 5), orchestration + reports (Task 6). We create the file in Task 4 and grow it.

- [ ] **Step 1: Write the failing test for scoring helpers**

Create `tests/test_benchmark_engines.py`:

```python
from __future__ import annotations

import importlib.util
from pathlib import Path


def load_driver_module():
    script_path = Path(__file__).parents[1] / "scripts" / "benchmark_engines.py"
    spec = importlib.util.spec_from_file_location("benchmark_engines", script_path)
    assert spec is not None and spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_normalize_text_collapses_whitespace_and_case() -> None:
    driver = load_driver_module()
    assert driver.normalize_text("  Hello   World\n") == "hello world"


def test_character_accuracy_perfect_match() -> None:
    driver = load_driver_module()
    assert driver.character_accuracy("invoice 8866", "invoice 8866") == 1.0


def test_character_accuracy_partial() -> None:
    driver = load_driver_module()
    # one char wrong out of 6 -> 5/6
    acc = driver.character_accuracy("abcdef", "abcxef")
    assert abs(acc - (5 / 6)) < 1e-9


def test_character_accuracy_empty_truth_is_one() -> None:
    driver = load_driver_module()
    assert driver.character_accuracy("", "") == 1.0


def test_edit_distance_basic() -> None:
    driver = load_driver_module()
    assert driver.edit_distance("kitten", "sitting") == 3


def test_exact_line_match_rate() -> None:
    driver = load_driver_module()
    truth = "line one\nline two\nline three"
    out = "line one\nline two\nwrong"
    # 2 of 3 lines match
    assert driver.exact_line_match_rate(truth, out) == 2 / 3


def test_median_latency() -> None:
    driver = load_driver_module()
    assert driver.median_latency([100, 200, 300, 400, 500]) == 300
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_benchmark_engines.py -v`
Expected: FAIL — `benchmark_engines` module not found.

- [ ] **Step 3: Write the scoring helpers**

Create `scripts/benchmark_engines.py` with just the helpers so far (more added in Task 5/6):

```python
from __future__ import annotations

import re
import statistics
from typing import Any


def normalize_text(text: str) -> str:
    """Lowercase, strip, collapse all whitespace runs to single spaces for scoring."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _levenshtein(a: str, b: str) -> int:
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def edit_distance(a: str, b: str) -> int:
    """Levenshtein edit distance between two strings."""
    return _levenshtein(a, b)


def character_accuracy(truth: str, candidate: str) -> float:
    """1 - edit_distance / len(truth). Empty truth is a perfect match (1.0)."""
    truth = normalize_text(truth)
    candidate = normalize_text(candidate)
    if not truth:
        return 1.0
    return 1.0 - (_levenshtein(truth, candidate) / len(truth))


def exact_line_match_rate(truth: str, candidate: str) -> float:
    """Fraction of truth lines that appear verbatim (after normalization) in output."""
    truth_lines = [normalize_text(ln) for ln in truth.splitlines() if ln.strip()]
    candidate_lines = {normalize_text(ln) for ln in candidate.splitlines() if ln.strip()}
    if not truth_lines:
        return 1.0
    matches = sum(1 for ln in truth_lines if ln in candidate_lines)
    return matches / len(truth_lines)


def median_latency(samples_ms: list[float]) -> float:
    return float(statistics.median(samples_ms))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_benchmark_engines.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Lint check**

Run: `uv run ruff check scripts/benchmark_engines.py tests/test_benchmark_engines.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add scripts/benchmark_engines.py tests/test_benchmark_engines.py
git commit -m "Add benchmark driver scoring helpers (accuracy, edit distance, latency)"
```

---

## Task 5: Driver — adapter subprocess protocol with a fake adapter

**Files:**
- Modify: `scripts/benchmark_engines.py` (add protocol layer)
- Modify: `tests/test_benchmark_engines.py` (add protocol test)

The driver talks to adapters over stdin/stdout JSON lines. To test it without a real engine, we use a tiny fake adapter script written to a temp file that echoes deterministic results.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_benchmark_engines.py`:

```python
def test_run_contender_collects_results_from_fake_adapter(tmp_path) -> None:
    driver = load_driver_module()
    # Fake adapter: echoes elapsed_ms=10 and text=fake for any image it receives.
    fake_adapter = tmp_path / "fake_adapter.py"
    fake_adapter.write_text(
        "import json, sys, time, pathlib\n"
        "for line in sys.stdin:\n"
        "    line=line.strip()\n"
        "    if not line: continue\n"
        "    req=json.loads(line)\n"
        "    res={'image':req['image'],'text':'fake','items':[],'elapsed_ms':10,'error':None}\n"
        "    sys.stdout.write(json.dumps(res)+'\\n'); sys.stdout.flush()\n",
        encoding="utf-8",
    )
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG")
    results = driver.run_contender(
        contender_id="fake",
        adapter_cmd=[_python(), str(fake_adapter)],
        images=[img],
        warmup=1,
        measured=2,
    )
    assert results["status"] == "ok"
    assert len(results["samples"]) == 1
    sample = results["samples"][0]
    assert sample["median_ms"] == 10
    assert len(sample["runs"]) == 2


def _python() -> str:
    import sys

    return sys.executable
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_benchmark_engines.py::test_run_contender_collects_results_from_fake_adapter -v`
Expected: FAIL — `AttributeError: module 'benchmark_engines' has no attribute 'run_contender'`.

- [ ] **Step 3: Implement run_contender**

Append to `scripts/benchmark_engines.py`.

First, add these imports at the top of the module alongside the existing ones (Task 4 added `difflib`, `re`, `statistics`, `typing.Any`):

```python
import json
import subprocess
import sys
import time
from pathlib import Path
```

Then append the function below at the end of the module:
```python
def run_contender(
    contender_id: str,
    adapter_cmd: list[str],
    images: list[Path],
    warmup: int,
    measured: int,
) -> dict[str, Any]:
    """Spawn one adapter subprocess, send each image (warmup+measured) times.

    Returns: {"contender_id", "status": "ok"|"unavailable"|"error", "fatal"?, "samples": [...]}
    Each sample: {"image": str, "median_ms": float, "runs": [int,...],
                  "text": str, "items": [...], "error": str|None}
    """
    try:
        proc = subprocess.Popen(
            adapter_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        return {"contender_id": contender_id, "status": "unavailable", "fatal": str(exc), "samples": []}

    samples: list[dict[str, Any]] = []
    for image in images:
        runs: list[int] = []
        last_text = ""
        last_items: list[dict[str, Any]] = []
        last_error: str | None = None
        for i in range(warmup + measured):
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(json.dumps({"image": str(image)}) + "\n")
            proc.stdin.flush()
            out_line = proc.stdout.readline()
            if not out_line:
                # adapter died mid-stream
                err = proc.stderr.read() if proc.stderr else ""
                return {
                    "contender_id": contender_id,
                    "status": "error",
                    "fatal": f"adapter closed stream: {err[:500]}",
                    "samples": samples,
                }
            parsed = json.loads(out_line)
            if parsed.get("fatal"):
                return {
                    "contender_id": contender_id,
                    "status": "unavailable",
                    "fatal": parsed["fatal"],
                    "samples": [],
                }
            if i >= warmup:  # only time measured runs
                runs.append(int(parsed.get("elapsed_ms", 0)))
            last_text = parsed.get("text", "")
            last_items = parsed.get("items", [])
            last_error = parsed.get("error")
        samples.append(
            {
                "image": str(image),
                "median_ms": median_latency(runs) if runs else 0.0,
                "runs": runs,
                "text": last_text,
                "items": last_items,
                "error": last_error,
            }
        )
    proc.stdin.close()
    proc.wait(timeout=30)
    return {"contender_id": contender_id, "status": "ok", "samples": samples}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_benchmark_engines.py -v`
Expected: PASS (8 tests, including the fake-adapter protocol test).

- [ ] **Step 5: Lint check**

Run: `uv run ruff check scripts/benchmark_engines.py tests/test_benchmark_engines.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add scripts/benchmark_engines.py tests/test_benchmark_engines.py
git commit -m "Add benchmark driver adapter subprocess protocol"
```

---

## Task 6: Driver — orchestration, scoring against ground truth, and reports

**Files:**
- Modify: `scripts/benchmark_engines.py` (add orchestration + reporting + main)
- Modify: `tests/test_benchmark_engines.py` (add aggregate-scoring test)

- [ ] **Step 1: Write the failing test for aggregation**

Append to `tests/test_benchmark_engines.py`:

```python
def test_score_contender_against_truth() -> None:
    driver = load_driver_module()
    truth = [{"image": "a.png", "category": "english-single", "text": "invoice 8866"}]
    contender = {
        "contender_id": "fake",
        "status": "ok",
        "samples": [
            {
                "image": str(Path("a.png")),
                "median_ms": 50.0,
                "runs": [50],
                "text": "invoice 8866",
                "items": [],
                "error": None,
            }
        ],
    }
    scored = driver.score_contender(contender, truth)
    assert scored["status"] == "ok"
    assert scored["median_ms_overall"] == 50.0
    assert scored["char_accuracy_overall"] == 1.0
    assert scored["exact_line_match_overall"] == 1.0
    assert scored["edit_distance_total"] == 0


def test_score_unavailable_contender() -> None:
    driver = load_driver_module()
    scored = driver.score_contender(
        {"contender_id": "rapidocr", "status": "unavailable", "fatal": "boom", "samples": []},
        [],
    )
    assert scored["status"] == "unavailable"
    assert scored["fatal"] == "boom"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest tests/test_benchmark_engines.py::test_score_contender_against_truth tests/test_benchmark_engines.py::test_score_unavailable_contender -v`
Expected: FAIL — `score_contender` not defined.

- [ ] **Step 3: Implement score_contender + reporting + main**

Append to `scripts/benchmark_engines.py`:

```python
CONTENDERS = [
    {
        "id": "paddleocr-default",
        "adapter": "paddleocr_adapter.py",
        "extra_args": ["--tier", "default"],
        "venv": ".venv-bench-paddleocr",
        "package": "paddleocr paddlepaddle pillow",
    },
    {
        "id": "paddleocr-mobile",
        "adapter": "paddleocr_adapter.py",
        "extra_args": ["--tier", "mobile"],
        "venv": ".venv-bench-paddleocr",
        "package": "paddleocr paddlepaddle pillow",
    },
    {
        "id": "rapidocr",
        "adapter": "rapidocr_adapter.py",
        "extra_args": [],
        "venv": ".venv-bench-rapidocr",
        "package": "rapidocr_onnxruntime pillow",
    },
]


def score_contender(contender: dict[str, Any], truth: list[dict[str, Any]]) -> dict[str, Any]:
    """Attach accuracy + latency aggregates to a contender's raw results."""
    if contender["status"] != "ok":
        return contender
    truth_by_image = {Path(t["image"]).name: t for t in truth}
    latencies: list[float] = []
    char_accs: list[float] = []
    line_rates: list[float] = []
    edit_total = 0
    for sample in contender["samples"]:
        latencies.append(sample["median_ms"])
        t = truth_by_image.get(Path(sample["image"]).name)
        if t is None:
            continue
        truth_text = t["text"]
        candidate = sample["text"] or ""
        char_accs.append(character_accuracy(truth_text, candidate))
        line_rates.append(exact_line_match_rate(truth_text, candidate))
        edit_total += _levenshtein(normalize_text(truth_text), normalize_text(candidate))
    contender["median_ms_overall"] = median_latency(latencies) if latencies else 0.0
    contender["char_accuracy_overall"] = sum(char_accs) / len(char_accs) if char_accs else 0.0
    contender["exact_line_match_overall"] = sum(line_rates) / len(line_rates) if line_rates else 0.0
    contender["edit_distance_total"] = edit_total
    return contender


def summarize(scored: list[dict[str, Any]]) -> str:
    """Render a human-readable summary table to a string."""
    header = f"{'contender':<22}{'status':<13}{'median_ms':>11}{'char_acc':>10}{'line_acc':>10}{'edit':>8}"
    lines = [header, "-" * len(header)]
    for c in scored:
        if c["status"] != "ok":
            lines.append(f"{c['contender_id']:<22}{c['status']:<13}{'-':>11}{'-':>10}{'-':>10}{'-':>8}")
            continue
        lines.append(
            f"{c['contender_id']:<22}{c['status']:<13}{c['median_ms_overall']:>11.0f}"
            f"{c['char_accuracy_overall']:>10.2%}{c['exact_line_match_overall']:>10.2%}"
            f"{c['edit_distance_total']:>8}"
        )
    return "\n".join(lines)


def main() -> None:
    import argparse
    import datetime as _dt
    import platform

    parser = argparse.ArgumentParser(description="Benchmark OCR engine contenders.")
    parser.add_argument("--fixtures", type=Path, default=Path("samples/benchmark"))
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--measured", type=int, default=5)
    parser.add_argument("--only", help="comma-separated contender ids to run")
    args = parser.parse_args()

    import benchmark_fixtures  # generated in fixtures dir; added to sys.path below

    truth_path = args.fixtures / "ground_truth.json"
    if not truth_path.exists():
        raise SystemExit(f"no fixtures at {truth_path}; run benchmark_fixtures.py first")
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    images = [args.fixtures / t["image"] for t in truth]

    adapters_dir = Path(__file__).parent / "benchmark_adapters"
    selected = (
        CONTENDERS
        if not args.only
        else [c for c in CONTENDERS if c["id"] in args.only.split(",")]
    )

    results: list[dict[str, Any]] = []
    for contender in selected:
        # Prefer the engine's own venv python if present, else fall back to current python.
        venv_python = Path(contender["venv"]) / ("Scripts" / "python.exe" if platform.system() == "Windows" else "bin/python")
        python = str(venv_python) if venv_python.exists() else sys.executable
        adapter_cmd = [python, str(adapters_dir / contender["adapter"]), *contender["extra_args"]]
        raw = run_contender(contender["id"], adapter_cmd, images, args.warmup, args.measured)
        results.append(score_contender(raw, truth))

    print(summarize(results))

    stamp = _dt.date.today().isoformat()
    out_json = Path("docs/verification") / f"{stamp}-engine-benchmark.json"
    out_md = Path("docs/verification") / f"{stamp}-engine-benchmark.md"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "host": platform.node(),
        "platform": platform.platform(),
        "python": sys.version,
        "warmup": args.warmup,
        "measured": args.measured,
        "contenders": results,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.write_text(
        f"# OCR Engine Benchmark {stamp}\n\nhost: {payload['host']} | {payload['platform']}\n\n"
        f"```\n{summarize(results)}\n```\n\n"
        f"Full data: {out_json.name}\n",
        encoding="utf-8",
    )
    print(f"\nwrote {out_json}\nwrote {out_md}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest tests/test_benchmark_engines.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Lint check**

Run: `uv run ruff check scripts/benchmark_engines.py tests/test_benchmark_engines.py`
Expected: `All checks passed!`

- [ ] **Step 6: Commit**

```bash
git add scripts/benchmark_engines.py tests/test_benchmark_engines.py
git commit -m "Add benchmark orchestration, scoring against ground truth, and report output"
```

---

## Task 7: README section + integration sanity check

**Files:**
- Modify: `README.md` (add a benchmark section)

- [ ] **Step 1: Add a benchmark section to README**

In `README.md`, after the "验证" (verification) section, add:

```markdown
## 引擎对比基准

对比 PaddleOCR(默认/轻量档)与 RapidOCR 的速度和精度(纯本地,基于带标准答案的合成图):

```bash
# 1. 生成测试图(跨平台;无中文字体时自动跳过中文图)
uv run python scripts/benchmark_fixtures.py

# 2. (可选)为各引擎建独立 venv,避免依赖冲突
uv venv .venv-bench-paddleocr && uv pip install --python .venv-bench-paddleocr paddleocr paddlepaddle pillow
uv venv .venv-bench-rapidocr && uv pip install --python .venv-bench-rapidocr rapidocr_onnxruntime pillow

# 3. 跑基准(默认预热 1 次、计时 5 次,取中位数)
uv run python scripts/benchmark_engines.py

# 只跑指定引擎
uv run python scripts/benchmark_engines.py --only paddleocr-default,rapidocr
```

报告写到 `docs/verification/<date>-engine-benchmark.{json,md}`。引擎未安装时会标记 `unavailable` 而不中断。
```

- [ ] **Step 2: Full test + lint run**

Run: `uv run --extra dev pytest -q && uv run ruff check .`
Expected: all tests PASS, lint clean.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Document OCR engine benchmark usage in README"
```

---

## Self-Review (run after writing, before handoff)

**1. Spec coverage:**
- Contenders (default/mobile/rapidocr) → Task 2 (paddleocr adapter both tiers) + Task 3 (rapidocr). ✓
- Fixtures (5 categories + ground truth + cross-platform CJK) → Task 1. ✓
- Process isolation (per-engine subprocess/venv) → Task 5 `run_contender` + Task 6 venv-python selection. ✓
- Measurement (warmup, measured N, median) → Task 4 `median_latency` + Task 5 loop. ✓
- Accuracy (char accuracy, edit distance, line match) → Task 4 + Task 6 `score_contender`. ✓
- Outputs (terminal + JSON + MD, dated) → Task 6 `main`. ✓
- Cross-platform (Mac + Windows) → font probe (Task 1), venv python path branching (Task 6). ✓
- Out of scope respected: no service changes, no `.env` switch, no PDF, no cloud. ✓

**2. Placeholder scan:** Cleaned during authoring — `edit_distance` delegates directly to a clean `_levenshtein` DP (no dead `difflib` opcode loop), and the Task 5 import instructions list exactly which imports to add with no stray placeholder lines. No remaining TBD/TODO.

**3. Type/signature consistency:** `run_contender` returns `samples` with keys `image/median_ms/runs/text/items/error`; `score_contender` reads exactly those plus the truth keys `image/text`. `median_latency`, `character_accuracy`, `exact_line_match_rate`, `_levenshtein`, `normalize_text` are defined in Task 4 and used unchanged in Tasks 5–6. Contender dict keys (`id/adapter/extra_args/venv/package`) are defined once in `CONTENDERS` (Task 6) and used consistently.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-19-engine-benchmark.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
