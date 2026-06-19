from __future__ import annotations

import re
import statistics


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
