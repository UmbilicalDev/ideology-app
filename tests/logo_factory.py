"""Generate tiny Party logo fixtures in code (no committed binaries)."""

import struct
import zlib


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def png(width: int = 1, height: int = 1, *, colour: int = 0) -> bytes:
    """A valid RGBA PNG of ``width`` x ``height`` pixels; ``colour`` varies the bytes."""
    row = b"\x00" + bytes([colour % 256, 0, 0, 255]) * width
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(row * height))
        + _chunk(b"IEND", b"")
    )


def png_of_size(size: int) -> bytes:
    """A PNG of exactly ``size`` bytes (padded with a private ``teXt`` chunk)."""
    base = png()
    pad = size - len(base) - 12
    assert pad >= 0
    return base[:-12] + _chunk(b"teXt", b"x" * pad) + base[-12:]


def webp(chunk: bytes = b"VP8L") -> bytes:
    """A minimal WebP container (RIFF size correct; only the header is checked)."""
    payload = b"\x2f\x00\x00\x00\x00\x00"
    body = b"WEBP" + chunk + struct.pack("<I", len(payload)) + payload
    return b"RIFF" + struct.pack("<I", len(body)) + body


SVG_NS = 'xmlns="http://www.w3.org/2000/svg"'


def svg(inner: str = '<rect width="10" height="10" fill="#123456"/>', *, attrs: str = "") -> bytes:
    """A passive SVG document (UTF-8)."""
    return (
        f'<svg {SVG_NS} viewBox="0 0 10 10"{(" " + attrs) if attrs else ""}>{inner}</svg>\n'
    ).encode()
