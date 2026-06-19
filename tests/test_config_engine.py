from __future__ import annotations


def test_engine_defaults_to_rapidocr() -> None:
    from paddleocr_service.config import Settings

    s = Settings(database_path="/tmp/x.sqlite3", output_dir="/tmp/o", upload_dir="/tmp/u")
    assert s.engine == "rapidocr"


def test_engine_reads_env_alias(monkeypatch) -> None:
    from paddleocr_service.config import Settings

    monkeypatch.setenv("PADDLEOCR_ENGINE", "paddleocr")
    s = Settings(database_path="/tmp/x.sqlite3", output_dir="/tmp/o", upload_dir="/tmp/u")
    assert s.engine == "paddleocr"
