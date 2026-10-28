"""The feedback message rule (feedback-api, Decision 1). Pure; no I/O.

The same rule lives in ``packages/core/src/domain/feedback.ts`` and both are
held equal by the shared test vectors. Steps, in order, on the raw string:

1. refuse C0/C1 controls other than ``\\n`` and any surrogate code point (in a
   Python ``str`` decoded from JSON a surrogate is always unpaired);
2. trim only ``TRIM_CHARS`` (ECMAScript ``String.prototype.trim``'s set; never
   bare ``str.strip()``, whose set differs);
3. count Unicode code points (``len``): empty or more than ``MAX_CHARS`` fails;
4. return the trimmed text, otherwise unchanged.
"""

import re

MAX_CHARS = 500

# ECMAScript WhiteSpace + LineTerminator: what JS ``String.prototype.trim`` removes.
TRIM_CHARS = (
    "\t\n\v\f\r \u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)

# C0 except ``\n``, DEL and C1, and every surrogate code point.
_REFUSED = re.compile("[\u0000-\u0009\u000b-\u001f\u007f-\u009f\ud800-\udfff]")

CONTROL_CHARACTER = "message must not contain control characters other than newline"
EMPTY = "message must not be empty"
TOO_LONG = f"message must be at most {MAX_CHARS} characters"


def clean_message(raw: str) -> str:
    """The trimmed message, or ``ValueError`` with the first problem found."""
    if _REFUSED.search(raw):
        raise ValueError(CONTROL_CHARACTER)
    text = raw.strip(TRIM_CHARS)
    if not text:
        raise ValueError(EMPTY)
    if len(text) > MAX_CHARS:
        raise ValueError(TOO_LONG)
    return text


def trim(raw: str) -> str:
    """``raw`` without leading or trailing ``TRIM_CHARS`` (used for the honeypot)."""
    return raw.strip(TRIM_CHARS)


__all__ = ["CONTROL_CHARACTER", "EMPTY", "MAX_CHARS", "TOO_LONG", "TRIM_CHARS", "clean_message", "trim"]
