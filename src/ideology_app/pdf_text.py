"""PDF text extraction. The only module that imports pypdf (see CONSTRAINTS.md).

There is no OCR: a PDF without a text layer is reported as a failure.
"""

import io
import logging

from pypdf import PdfReader
from pypdf.errors import DependencyError, FileNotDecryptedError

# pypdf reports recoverable problems (e.g. "EOF marker not found") through
# logging; keep the CLI output clean.
logging.getLogger("pypdf").setLevel(logging.ERROR)

ENCRYPTED = "PDF is encrypted"
NO_PAGES = "PDF has no pages"
NO_TEXT_LAYER = "no text layer found (scanned PDF?); OCR is not supported"
_REASON_MAX = 500


class PdfTextError(Exception):
    """Text could not be extracted. ``reason`` is stored as the failure reason."""

    def __init__(self, reason: str, page_count: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.page_count = page_count


def _read_error(exc: Exception) -> str:
    return f"could not read PDF: {type(exc).__name__}: {exc}"[:_REASON_MAX]


def extract_pages(data: bytes) -> list[str]:
    """Return the text of each page in page order, with NUL characters removed.

    Pages without text inside a document that has text elsewhere stay ``""`` so
    the page mapping is kept. Raises PdfTextError.
    """
    page_count: int | None = None
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                decrypted = reader.decrypt("")
            except (FileNotDecryptedError, DependencyError):
                raise PdfTextError(ENCRYPTED) from None
            if not decrypted:
                raise PdfTextError(ENCRYPTED)
        page_count = len(reader.pages)
        pages = [(page.extract_text() or "").replace("\x00", "") for page in reader.pages]
    except PdfTextError:
        raise
    except (FileNotDecryptedError, DependencyError):
        raise PdfTextError(ENCRYPTED, page_count) from None
    except Exception as exc:  # malformed PDFs raise assorted exception types
        raise PdfTextError(_read_error(exc), page_count) from None

    if not pages:
        raise PdfTextError(NO_PAGES, 0)
    if not any(text.strip() for text in pages):
        raise PdfTextError(NO_TEXT_LAYER, len(pages))
    return pages
