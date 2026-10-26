"""Party logos: the only gate through which logo bytes enter the database.

Pure (standard library only, no database): ``check_logo`` decides the media
type by content, never by extension, and refuses anything that is not a small
PNG, WebP or a passive SVG (no script, event handlers, entities, stylesheets
or external references). The app serves the stored bytes itself
(``GET /api/v1/parties/{id}/logo``) with ``nosniff`` and a sandbox CSP, the
second layer of SVG safety. See ``docs/specs/party-logos-data.md``.
"""

import hashlib
import re
import struct
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ideology_app.elections import InvalidInputError

MAX_LOGO_BYTES = 256 * 1024

PNG = "image/png"
WEBP = "image/webp"
SVG = "image/svg+xml"
MEDIA_TYPES = (PNG, WEBP, SVG)
EXTENSION_MEDIA_TYPES = {".png": PNG, ".webp": WEBP, ".svg": SVG}

NOT_AN_IMAGE = "not a PNG, WebP or SVG image"

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_IEND = b"\x00\x00\x00\x00IEND\xaeB`\x82"
_WEBP_CHUNKS = (b"VP8 ", b"VP8L", b"VP8X")
_SVG_ROOT = "{http://www.w3.org/2000/svg}svg"
_ALLOWED_DATA_PREFIXES = (
    "data:image/png",
    "data:image/jpeg",
    "data:image/gif",
    "data:image/webp",
)
_DOCTYPE_SUBSET_RE = re.compile(r"<!DOCTYPE[^>]*\[", re.IGNORECASE)
_CSS_URL_RE = re.compile(r"url\(\s*['\"]?\s*([^'\")\s]*)", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")


class InvalidLogoError(InvalidInputError):
    """A logo file or its bytes are refused. The message names the problem."""


class LogoChange(StrEnum):
    """What ``elections.set_party_logo`` did."""

    SET = "set"
    REPLACED = "replaced"
    REMOVED = "removed"
    UNCHANGED = "unchanged"
    NONE = "none"


@dataclass(frozen=True)
class Logo:
    """Checked logo bytes, their media type (by content) and lowercase hex SHA-256."""

    data: bytes
    media_type: str
    sha256: str

    def __repr__(self) -> str:
        return f"Logo(media_type={self.media_type!r}, bytes={len(self.data)}, sha256={self.sha256!r})"


def logo_version(sha256: str) -> str:
    """The cache-busting ``v`` of a logo URL: the first 16 hex characters of its SHA-256."""
    return sha256[:16]


def logo_url(party_id: int, sha256: str | None) -> str | None:
    """``/api/v1/parties/{id}/logo?v=<sha256[:16]>``, or ``None`` without a logo."""
    if sha256 is None:
        return None
    return f"/api/v1/parties/{party_id}/logo?v={logo_version(sha256)}"


def _is_png(data: bytes) -> bool:
    if len(data) < 8 + 25 + 12 or not data.startswith(_PNG_SIGNATURE):
        return False
    length, chunk_type, width, height = struct.unpack(">I4sII", data[8:24])
    return (
        length == 13
        and chunk_type == b"IHDR"
        and width >= 1
        and height >= 1
        and data.endswith(_PNG_IEND)
    )


def _is_webp(data: bytes) -> bool:
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        return False
    (size,) = struct.unpack("<I", data[4:8])
    return size == len(data) - 8 and data[12:16] in _WEBP_CHUNKS


def _local_name(name: str) -> str:
    return name.rsplit("}", 1)[-1]


def _check_reference(value: str) -> None:
    target = value.strip()
    if target.startswith("#") or target.startswith(_ALLOWED_DATA_PREFIXES):
        return
    raise InvalidLogoError(f"SVG logo has an external reference {target[:80]!r}")


def _check_css(text: str) -> None:
    if "@import" in text.lower():
        raise InvalidLogoError("SVG logo must not contain @import")
    for match in _CSS_URL_RE.finditer(text):
        _check_reference(match.group(1))


def _check_svg(data: bytes) -> None:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise InvalidLogoError(NOT_AN_IMAGE) from None
    if not text.lstrip().startswith("<"):
        raise InvalidLogoError(NOT_AN_IMAGE)
    if "<!ENTITY" in text.upper():
        raise InvalidLogoError("SVG logo must not declare entities (<!ENTITY)")
    if _DOCTYPE_SUBSET_RE.search(text):
        raise InvalidLogoError("SVG logo must not have a DOCTYPE internal subset")
    if "<?xml-stylesheet" in text.lower():
        raise InvalidLogoError("SVG logo must not reference a stylesheet (<?xml-stylesheet)")
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        raise InvalidLogoError(NOT_AN_IMAGE) from None
    if root.tag != _SVG_ROOT:
        raise InvalidLogoError(NOT_AN_IMAGE)
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        local = _local_name(element.tag).lower()
        if local == "script":
            raise InvalidLogoError("SVG logo must not contain <script>")
        if local == "foreignobject":
            raise InvalidLogoError("SVG logo must not contain <foreignObject>")
        if local == "style" and element.text:
            _check_css(element.text)
        for name, value in element.attrib.items():
            attribute = _local_name(name).lower()
            if attribute.startswith("on"):
                raise InvalidLogoError(
                    f"SVG logo must not have event handler attributes ({_local_name(name)!r})"
                )
            if "javascript:" in _SPACE_RE.sub("", value).lower():
                raise InvalidLogoError("SVG logo must not contain javascript: URLs")
            if attribute == "href":
                _check_reference(value)
            elif "url(" in value.lower() or attribute == "style":
                _check_css(value)


def _media_type(data: bytes) -> str:
    if _is_png(data):
        return PNG
    if _is_webp(data):
        return WEBP
    _check_svg(data)
    return SVG


def check_logo(data: bytes) -> Logo:
    """Check ``data`` and return it as a ``Logo``. Raises InvalidLogoError.

    PNG and WebP are recognised by their headers; anything else must be a
    passive SVG. At most ``MAX_LOGO_BYTES``; never empty.
    """
    if not data:
        raise InvalidLogoError("logo is empty")
    if len(data) > MAX_LOGO_BYTES:
        raise InvalidLogoError(f"logo is larger than {MAX_LOGO_BYTES} bytes")
    media_type = _media_type(data)
    return Logo(data=bytes(data), media_type=media_type, sha256=hashlib.sha256(data).hexdigest())


def read_logo_file(path: Path) -> Logo:
    """Read and check a logo file (a regular file, not a symlink). Raises InvalidLogoError.

    The size is checked with ``stat`` before the file is read.
    """
    file = Path(path)
    if file.is_symlink():
        raise InvalidLogoError("logo file must not be a symbolic link")
    if not file.exists():
        raise InvalidLogoError("logo file not found")
    if not file.is_file():
        raise InvalidLogoError("logo file is not a regular file")
    size = file.stat().st_size
    if size == 0:
        raise InvalidLogoError("logo is empty")
    if size > MAX_LOGO_BYTES:
        raise InvalidLogoError(f"logo is larger than {MAX_LOGO_BYTES} bytes")
    try:
        data = file.read_bytes()
    except OSError as exc:
        raise InvalidLogoError(f"cannot read logo file: {exc.strerror or exc}") from None
    return check_logo(data)
