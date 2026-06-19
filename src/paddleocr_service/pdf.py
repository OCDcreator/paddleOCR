from __future__ import annotations

from io import BytesIO

import pypdfium2


def render_pdf_pages(pdf_bytes: bytes, scale: float = 2.0) -> list[bytes]:
    document = pypdfium2.PdfDocument(pdf_bytes)
    pages: list[bytes] = []
    for page in document:
        bitmap = page.render(scale=scale)
        image = bitmap.to_pil()
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        pages.append(buffer.getvalue())
    return pages
