from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class JobRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_units INTEGER NOT NULL,
                    completed_units INTEGER NOT NULL,
                    documents_json TEXT NOT NULL,
                    error TEXT,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    source_payload_json TEXT,
                    output_json_path TEXT,
                    output_txt_path TEXT,
                    output_markdown_path TEXT,
                    canceled INTEGER NOT NULL DEFAULT 0
                )
                """
            )

    def upsert(self, job: Any) -> None:
        data = job.to_dict(include_source_payload=True, include_output_paths=True)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, kind, status, total_units, completed_units, documents_json, error,
                    created_at, started_at, finished_at, source_payload_json, output_json_path,
                    output_txt_path, output_markdown_path, canceled
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    kind=excluded.kind,
                    status=excluded.status,
                    total_units=excluded.total_units,
                    completed_units=excluded.completed_units,
                    documents_json=excluded.documents_json,
                    error=excluded.error,
                    started_at=excluded.started_at,
                    finished_at=excluded.finished_at,
                    source_payload_json=excluded.source_payload_json,
                    output_json_path=excluded.output_json_path,
                    output_txt_path=excluded.output_txt_path,
                    output_markdown_path=excluded.output_markdown_path,
                    canceled=excluded.canceled
                """,
                (
                    data["id"],
                    data["kind"],
                    data["status"],
                    data["total_units"],
                    data["completed_units"],
                    json.dumps(data["documents"], ensure_ascii=False),
                    data["error"],
                    data["created_at"],
                    data["started_at"],
                    data["finished_at"],
                    json.dumps(data.get("source_payload"), ensure_ascii=False),
                    data.get("output_paths", {}).get("json"),
                    data.get("output_paths", {}).get("txt"),
                    data.get("output_paths", {}).get("markdown"),
                    1 if data.get("canceled") else 0,
                ),
            )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row is not None else None

    def list_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    def delete(self, job_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            return cursor.rowcount > 0

    def list_expired(self, cutoff_timestamp: float) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM jobs
                WHERE COALESCE(finished_at, created_at) < ?
                ORDER BY created_at ASC
                """,
                (cutoff_timestamp,),
            ).fetchall()
        return [_row_to_job(row) for row in rows]


def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    output_paths = {
        "json": row["output_json_path"],
        "txt": row["output_txt_path"],
        "markdown": row["output_markdown_path"],
    }
    return {
        "id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "total_units": row["total_units"],
        "completed_units": row["completed_units"],
        "documents": json.loads(row["documents_json"]),
        "error": row["error"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "source_payload": json.loads(row["source_payload_json"])
        if row["source_payload_json"]
        else None,
        "output_paths": {key: value for key, value in output_paths.items() if value},
        "canceled": bool(row["canceled"]),
    }
