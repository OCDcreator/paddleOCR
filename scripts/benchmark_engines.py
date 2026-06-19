from __future__ import annotations

import json
import re
import statistics
import subprocess
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
