from paddleocr_service.config import Settings


def test_cors_origins_parse_from_comma_separated_env(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("PADDLEOCR_CORS_ORIGINS", "http://phone.local,http://tablet.local")
    monkeypatch.setenv("PADDLEOCR_ACCESS_LOG_PATH", str(tmp_path / "access.log"))

    settings = Settings()

    assert settings.cors_origins == ["http://phone.local", "http://tablet.local"]
    assert settings.access_log_path == tmp_path / "access.log"
