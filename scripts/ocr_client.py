from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Call the PaddleOCR LAN service.")
    parser.add_argument("image", type=Path, help="Path to one image file.")
    parser.add_argument("--url", default="http://127.0.0.1:8866/ocr")
    args = parser.parse_args()

    with args.image.open("rb") as image_file:
        response = httpx.post(
            args.url,
            files={"image": (args.image.name, image_file, "image/png")},
            timeout=120,
        )
    response.raise_for_status()
    print(json.dumps(response.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
