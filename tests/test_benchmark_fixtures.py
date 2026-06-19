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
