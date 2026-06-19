from __future__ import annotations

import json
import re
import statistics
import subprocess
import sys
from pathlib import Path
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


def run_contender(
    contender_id: str,
    adapter_cmd: list[str],
    images: list[Path],
    warmup: int,
    measured: int,
) -> dict[str, Any]:
    """Spawn one adapter subprocess, send each image (warmup+measured) times.

    Protocol: write one JSON request line per image to stdin
    ({"image": "<abs path>"}); the adapter writes one JSON result line to stdout.
    A result with a "fatal" key marks the contender unavailable.

    Returns: {"contender_id", "status": "ok"|"unavailable"|"error",
              "fatal"?, "samples": [...]}
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
        return {
            "contender_id": contender_id,
            "status": "unavailable",
            "fatal": str(exc),
            "samples": [],
        }

    samples: list[dict[str, Any]] = []
    assert proc.stdin is not None and proc.stdout is not None
    for image in images:
        runs: list[int] = []
        last_text = ""
        last_items: list[dict[str, Any]] = []
        last_error: str | None = None
        for i in range(warmup + measured):
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
    header = (
        f"{'contender':<22}{'status':<13}{'median_ms':>11}"
        f"{'char_acc':>10}{'line_acc':>10}{'edit':>8}"
    )
    lines = [header, "-" * len(header)]
    for c in scored:
        if c["status"] != "ok":
            lines.append(
                f"{c['contender_id']:<22}{c['status']:<13}"
                f"{'-':>11}{'-':>10}{'-':>10}{'-':>8}"
            )
            continue
        lines.append(
            f"{c['contender_id']:<22}{c['status']:<13}{c['median_ms_overall']:>11.0f}"
            f"{c['char_accuracy_overall']:>10.2%}{c['exact_line_match_overall']:>10.2%}"
            f"{c['edit_distance_total']:>8}"
        )
    return "\n".join(lines)


def main() -> None:
    import argparse
    import datetime as dt
    import platform

    parser = argparse.ArgumentParser(description="Benchmark OCR engine contenders.")
    parser.add_argument("--fixtures", type=Path, default=Path("samples/benchmark"))
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--measured", type=int, default=5)
    parser.add_argument("--only", help="comma-separated contender ids to run")
    args = parser.parse_args()

    truth_path = args.fixtures / "ground_truth.json"
    if not truth_path.exists():
        raise SystemExit(
            f"no fixtures at {truth_path}; run benchmark_fixtures.py first"
        )
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
        bin_dir = "Scripts" if platform.system() == "Windows" else "bin"
        venv_python = Path(contender["venv"]) / bin_dir / (
            "python.exe" if platform.system() == "Windows" else "python"
        )
        python = str(venv_python) if venv_python.exists() else sys.executable
        adapter_cmd = [
            python,
            str(adapters_dir / contender["adapter"]),
            *contender["extra_args"],
        ]
        raw = run_contender(contender["id"], adapter_cmd, images, args.warmup, args.measured)
        results.append(score_contender(raw, truth))

    print(summarize(results))

    stamp = dt.date.today().isoformat()
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
        f"# OCR Engine Benchmark {stamp}\n\n"
        f"host: {payload['host']} | {payload['platform']}\n\n"
        f"```\n{summarize(results)}\n```\n\n"
        f"Full data: {out_json.name}\n",
        encoding="utf-8",
    )
    print(f"\nwrote {out_json}\nwrote {out_md}")


if __name__ == "__main__":
    main()

