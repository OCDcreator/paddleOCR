from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

import httpx


def upload(client: httpx.Client, url: str, field_name: str, path: Path, content_type: str) -> dict:
    with path.open("rb") as file:
        response = client.post(
            url,
            files={field_name: (path.name, file, content_type)},
        )
    response.raise_for_status()
    return response.json()


def wait_for_job(client: httpx.Client, base_url: str, job_id: str, timeout_seconds: int) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = client.get(f"{base_url}/jobs/{job_id}")
        response.raise_for_status()
        data = response.json()
        if data["status"] in {"succeeded", "failed", "canceled"}:
            return data
        time.sleep(0.5)
    raise TimeoutError(f"Job {job_id} did not finish in {timeout_seconds}s")


def download_text(client: httpx.Client, base_url: str, job_id: str, output_format: str) -> str:
    response = client.get(f"{base_url}/jobs/{job_id}/download/{output_format}")
    response.raise_for_status()
    return response.text


def submit_batch(client: httpx.Client, base_url: str, image: Path) -> dict:
    with image.open("rb") as first, image.open("rb") as second:
        response = client.post(
            f"{base_url}/jobs/images",
            files=[
                ("images", (image.name, first.read(), "image/png")),
                ("images", (image.name, second.read(), "image/png")),
            ],
        )
    response.raise_for_status()
    return response.json()


def exercise_queue_controls(
    client: httpx.Client,
    base_url: str,
    image: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    client.post(f"{base_url}/queue/pause").raise_for_status()
    submitted = submit_batch(client, base_url, image)
    canceled = client.post(f"{base_url}/jobs/{submitted['id']}/cancel")
    canceled.raise_for_status()
    retried = client.post(f"{base_url}/jobs/{submitted['id']}/retry")
    retried.raise_for_status()
    client.post(f"{base_url}/queue/resume").raise_for_status()
    completed = wait_for_job(client, base_url, submitted["id"], timeout_seconds)
    return {
        "job_id": submitted["id"],
        "canceled_status": canceled.json()["status"],
        "retry_status": retried.json()["status"],
        "final_status": completed["status"],
    }


def check_settings_validation(client: httpx.Client, base_url: str) -> dict[str, int]:
    invalid_payloads = {
        "bad_upload_limit": {"max_upload_bytes": 0},
        "bad_pdf_scale": {"pdf_render_scale": 0},
        "bad_retention": {"retention_days": -1},
    }
    results: dict[str, int] = {}
    for name, payload in invalid_payloads.items():
        response = client.patch(f"{base_url}/settings", json=payload)
        results[name] = response.status_code
        if response.status_code != 422:
            response.raise_for_status()
            raise AssertionError(f"{name} returned {response.status_code}, expected 422")
    return results


def check_cors_preflight(client: httpx.Client, base_url: str) -> dict[str, Any]:
    response = client.options(
        f"{base_url}/jobs",
        headers={
            "Origin": "http://phone.local",
            "Access-Control-Request-Method": "GET",
        },
    )
    return {
        "status_code": response.status_code,
        "allow_origin": response.headers.get("access-control-allow-origin"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Functional smoke test for the OCR service.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8866")
    parser.add_argument("--image", type=Path, default=Path("samples/ocr_sample.png"))
    parser.add_argument("--pdf", type=Path, default=Path("samples/ocr_sample.pdf"))
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    with httpx.Client(timeout=args.timeout) as client:
        health = client.get(f"{args.base_url}/health")
        health.raise_for_status()

        settings_before = client.get(f"{args.base_url}/settings")
        settings_before.raise_for_status()
        settings_payload = settings_before.json()
        settings_validation = check_settings_validation(client, args.base_url)
        cors_preflight = check_cors_preflight(client, args.base_url)
        settings_update = client.patch(
            f"{args.base_url}/settings",
            json={
                "language": settings_payload["language"],
                "pdf_render_scale": settings_payload["pdf_render_scale"],
                "save_uploads": settings_payload["save_uploads"],
                "retention_days": settings_payload["retention_days"],
                "max_upload_bytes": settings_payload["max_upload_bytes"],
                "warmup_on_startup": settings_payload["warmup_on_startup"],
            },
        )
        settings_update.raise_for_status()

        single = upload(client, f"{args.base_url}/ocr", "image", args.image, "image/png")

        batch_job = submit_batch(client, args.base_url, args.image)
        batch = wait_for_job(client, args.base_url, batch_job["id"], args.timeout)

        pdf_job = upload(client, f"{args.base_url}/jobs/pdf", "pdf", args.pdf, "application/pdf")
        pdf = wait_for_job(client, args.base_url, pdf_job["id"], args.timeout)

        history = client.get(f"{args.base_url}/jobs")
        history.raise_for_status()

        json_output = download_text(client, args.base_url, batch["id"], "json")
        txt_output = download_text(client, args.base_url, batch["id"], "txt")
        markdown_output = download_text(client, args.base_url, batch["id"], "markdown")

        queue_controls = exercise_queue_controls(client, args.base_url, args.image, args.timeout)
        retention_cleanup = client.post(f"{args.base_url}/operations/retention/cleanup")
        retention_cleanup.raise_for_status()

        delete_response = client.delete(f"{args.base_url}/jobs/{batch['id']}")
        delete_response.raise_for_status()
        deleted_detail = client.get(f"{args.base_url}/jobs/{batch['id']}")

        final_health = client.get(f"{args.base_url}/health")
        final_health.raise_for_status()

    summary = {
        "health_status": health.json()["status"],
        "settings_round_trip": settings_update.json(),
        "settings_validation_statuses": settings_validation,
        "cors_preflight": cors_preflight,
        "single_text": single["text"],
        "batch_status": batch["status"],
        "batch_documents": len(batch["documents"]),
        "pdf_status": pdf["status"],
        "pdf_pages": len(pdf["documents"][0]["pages"]) if pdf["documents"] else 0,
        "history_count": len(history.json()["jobs"]),
        "download_json_has_job_id": batch["id"] in json_output,
        "download_txt_chars": len(txt_output),
        "download_markdown_has_heading": "# OCR Job" in markdown_output,
        "queue_controls": queue_controls,
        "retention_cleanup": retention_cleanup.json(),
        "delete_status_code_after_delete": deleted_detail.status_code,
        "final_queue": final_health.json()["queue"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
