from __future__ import annotations

import json
from typing import Any


def render_json(job: dict[str, Any]) -> str:
    return json.dumps(job, ensure_ascii=False, indent=2)


def render_text(job: dict[str, Any]) -> str:
    lines: list[str] = []
    for document in job.get("documents", []):
        lines.append(f"## {document.get('filename', 'document')}")
        for page in document.get("pages", []):
            lines.append(f"[Page {page.get('page_number', 1)}]")
            text = page.get("text", "")
            if text:
                lines.append(text)
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_markdown(job: dict[str, Any]) -> str:
    lines = [
        f"# OCR Job {job['id']}",
        "",
        f"- Status: {job['status']}",
        f"- Kind: {job['kind']}",
        "",
    ]
    for document in job.get("documents", []):
        lines.extend([f"## {document.get('filename', 'document')}", ""])
        for page in document.get("pages", []):
            lines.extend([f"### Page {page.get('page_number', 1)}", ""])
            text = page.get("text", "")
            lines.extend([text if text else "_No text recognized._", ""])
    return "\n".join(lines).strip() + "\n"
