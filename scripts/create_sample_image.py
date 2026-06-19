from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def main() -> None:
    output = Path("samples/ocr_sample.png")
    output.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGB", (900, 300), color="white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(64)
    body_font = load_font(46)

    draw.text((90, 40), "PaddleOCR LAN Test", fill="black", font=title_font)
    draw.text((90, 145), "Invoice No: OCR-8866", fill="black", font=body_font)
    draw.text((90, 210), "Amount: 123.45 USD", fill="black", font=body_font)

    image.save(output)
    print(output)


if __name__ == "__main__":
    main()
