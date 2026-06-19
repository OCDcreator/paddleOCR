from __future__ import annotations

import importlib.util
from pathlib import Path


def load_driver_module():
    script_path = Path(__file__).parents[1] / "scripts" / "benchmark_engines.py"
    spec = importlib.util.spec_from_file_location("benchmark_engines", script_path)
    assert spec is not None and spec.loader is not None
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
