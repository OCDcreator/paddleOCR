from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Literal

from paddleocr_service.config import Settings
from paddleocr_service.exports import render_json, render_markdown, render_text

OutputFormat = Literal["json", "txt", "markdown"]

OUTPUT_FILENAMES: dict[OutputFormat, str] = {
    "json": "result.json",
    "txt": "result.txt",
    "markdown": "result.md",
}


class LocalStorage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def ensure_base_dirs(self) -> None:
        self.settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.settings.output_dir.mkdir(parents=True, exist_ok=True)
        if self.settings.save_uploads:
            self.settings.upload_dir.mkdir(parents=True, exist_ok=True)

    def save_upload(self, job_id: str, filename: str, payload: bytes) -> Path | None:
        if not self.settings.save_uploads:
            return None
        safe_name = _safe_filename(filename)
        upload_dir = self.settings.upload_dir / job_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        path = upload_dir / safe_name
        path.write_bytes(payload)
        return path

    def save_outputs(self, job: dict[str, Any]) -> dict[str, Path]:
        output_dir = self.job_output_dir(job["id"])
        output_dir.mkdir(parents=True, exist_ok=True)
        rendered = {
            "json": render_json(job),
            "txt": render_text(job),
            "markdown": render_markdown(job),
        }
        paths: dict[str, Path] = {}
        for key, text in rendered.items():
            path = output_dir / OUTPUT_FILENAMES[key]  # type: ignore[index]
            path.write_text(text, encoding="utf-8")
            paths[key] = path
        return paths

    def output_path(self, job_id: str, output_format: OutputFormat) -> Path:
        return self.job_output_dir(job_id) / OUTPUT_FILENAMES[output_format]

    def output_urls(self, job_id: str) -> dict[str, str]:
        return {
            key: f"/jobs/{job_id}/download/{key}"
            for key in OUTPUT_FILENAMES
            if self.output_path(job_id, key).exists()
        }

    def job_output_dir(self, job_id: str) -> Path:
        return self.settings.output_dir / job_id

    def delete_job_files(self, job_id: str) -> None:
        shutil.rmtree(self.settings.output_dir / job_id, ignore_errors=True)
        shutil.rmtree(self.settings.upload_dir / job_id, ignore_errors=True)

    def output_bytes(self) -> int:
        return _directory_size(self.settings.output_dir)

    def upload_bytes(self) -> int:
        return _directory_size(self.settings.upload_dir)


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    return name or "upload.bin"
