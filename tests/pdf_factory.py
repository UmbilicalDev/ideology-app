"""Build small PDFs for tests, so no binary fixtures are committed."""

import io


def _escape(line: str) -> bytes:
    raw = line.encode("cp1252")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _content(text: str | None) -> bytes:
    if text is None:
        # A filled rectangle only: a page with no text layer.
        return b"0 0 1 rg 10 10 100 100 re f"
    parts = []
    y = 720
    for line in text.split("\n"):
        parts.append(b"BT /F1 12 Tf 72 %d Td (" % y + _escape(line) + b") Tj ET")
        y -= 16
    return b"\n".join(parts)


def make_text_pdf(pages: list[str | None]) -> bytes:
    """Return a minimal PDF with one page per item; ``None`` is a page without text."""
    n = len(pages)
    font_id = 3
    first_page_id = 4
    page_ids = [first_page_id + 2 * i for i in range(n)]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids ["
        + b" ".join(b"%d 0 R" % pid for pid in page_ids)
        + b"] /Count %d >>" % n,
        font_id: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>",
    }
    for pid, text in zip(page_ids, pages):
        stream = _content(text)
        objects[pid] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>" % (font_id, pid + 1)
        )
        objects[pid + 1] = b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for obj_id in sorted(objects):
        offsets[obj_id] = out.tell()
        out.write(b"%d 0 obj\n" % obj_id + objects[obj_id] + b"\nendobj\n")
    size = max(objects) + 1
    xref_at = out.tell()
    out.write(b"xref\n0 %d\n" % size)
    out.write(b"0000000000 65535 f \n")
    for obj_id in range(1, size):
        out.write(b"%010d 00000 n \n" % offsets[obj_id])
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (size, xref_at))
    return out.getvalue()


def encrypt_pdf(data: bytes, user_password: str) -> bytes:
    """Return ``data`` encrypted with RC4 (no ``cryptography`` needed)."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
    writer.encrypt(user_password, "owner-secret", algorithm="RC4-128")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def blank_pdf(pages: int = 1) -> bytes:
    """A valid PDF made with pypdf's ``add_blank_page``: no text at all."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(612, 792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()
