from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# CJK font candidates per platform, in preference order.
CJK_FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    # Windows
    "C:/Windows/Fonts/msyh.ttc",      # Microsoft YaHei
    "C:/Windows/Fonts/simhei.ttf",    # SimHei
    # Linux
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def probe_cjk_font() -> Path | None:
    """Return the first available CJK font path, or None if none found."""
    for candidate in CJK_FONT_CANDIDATES:
        if Path(candidate).exists():
            return Path(candidate)
    return None


# Each entry: (category, text, needs_cjk, width, height, font_size)
FIXTURE_SPECS = [
    ("english-single", "Invoice No: OCR-8866\nAmount: 123.45 USD", False, 600, 160, 32),
    ("chinese-multiline", "你好世界\n中文识别测试\n局域网 OCR", True, 600, 240, 36),
    ("mixed-zh-en", "金额 123.45 USD\n日期 2026-06-19", True, 600, 160, 32),
    ("dense-multiline", "\n".join(f"Line {i}: value {i}" for i in range(12)), False, 700, 480, 26),
    ("large-resolution", "Big Canvas OCR Test\nResolution stress", False, 1600, 900, 48),
]


def _draw_image(
    text: str, width: int, height: int, font_size: int, font_path: Path | None
) -> bytes:
    image = Image.new("RGB", (width, height), color="white")
    draw = ImageDraw.Draw(image)
    if font_path is not None:
        try:
            font = ImageFont.truetype(str(font_path), font_size)
        except OSError:
            font = ImageFont.load_default()
    else:
        font = ImageFont.load_default()
    # Draw each line stacked from a top margin.
    y = 20
    for line in text.split("\n"):
        draw.text((20, y), line, fill="black", font=font)
        y += font_size + 12
    from io import BytesIO

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def generate_all(out_dir: Path) -> list[dict]:
    """Generate all fixture images + ground_truth.json. Returns the truth list.

    CJK-requiring categories are skipped (and recorded) when no CJK font is found,
    so the benchmark still runs on a host without CJK fonts.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    cjk_font = probe_cjk_font()
    truth: list[dict] = []
    for category, text, needs_cjk, width, height, font_size in FIXTURE_SPECS:
        if needs_cjk and cjk_font is None:
            continue  # skip CJK category on hosts without a CJK font
        font_path = cjk_font if needs_cjk else None
        filename = f"{category}.png"
        (out_dir / filename).write_bytes(_draw_image(text, width, height, font_size, font_path))
        truth.append(
            {"image": filename, "category": category, "text": text, "needs_cjk": needs_cjk}
        )
    (out_dir / "ground_truth.json").write_text(
        json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return truth


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate OCR benchmark fixtures.")
    parser.add_argument("--out", type=Path, default=Path("samples/benchmark"))
    args = parser.parse_args()
    truth = generate_all(args.out)
    cjk = probe_cjk_font() is not None
    print(f"wrote {len(truth)} fixtures to {args.out}")
    print(f"cjk_font_available={cjk}")
    if not cjk:
        print("note: CJK categories skipped because no CJK font was found")


if __name__ == "__main__":
    main()
