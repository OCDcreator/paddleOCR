from __future__ import annotations

from pathlib import Path

from PIL import (
    Image,
    ImageDraw,
    ImageFont,
    JpegImagePlugin,  # noqa: F401
)


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


def make_page(title: str, line: str) -> Image.Image:
    image = Image.new("RGB", (900, 300), color="white")
    draw = ImageDraw.Draw(image)
    title_font = load_font(64)
    body_font = load_font(46)
    draw.text((90, 56), title, fill="black", font=title_font)
    draw.text((90, 170), line, fill="black", font=body_font)
    return image


def main() -> None:
    output = Path("samples/ocr_sample.pdf")
    output.parent.mkdir(parents=True, exist_ok=True)
    pages = [
        make_page("PaddleOCR PDF Page 1", "Batch Code: PDF-001"),
        make_page("PaddleOCR PDF Page 2", "Total: 678.90 USD"),
    ]
    pages[0].save(output, save_all=True, append_images=pages[1:])
    print(output)


if __name__ == "__main__":
    main()
