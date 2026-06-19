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


def _python() -> str:
    import sys

    return sys.executable


def test_run_contender_collects_results_from_fake_adapter(tmp_path) -> None:
    driver = load_driver_module()
    # Fake adapter: echoes elapsed_ms=10 and text=fake for any image it receives.
    fake_adapter = tmp_path / "fake_adapter.py"
    fake_adapter.write_text(
        "import json, sys\n"
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


def test_run_contender_reports_unavailable_when_cmd_missing() -> None:
    driver = load_driver_module()
    results = driver.run_contender(
        contender_id="missing",
        adapter_cmd=["definitely-not-a-real-binary-xyz", "arg"],
        images=[],
        warmup=0,
        measured=1,
    )
    assert results["status"] == "unavailable"
    assert results["samples"] == []


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


