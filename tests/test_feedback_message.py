"""feedback-api Scenario 2: the message rule (Decision 1).

The same vectors are in ``packages/core/test/domain/feedback.test.ts``; keep
the two tables equal.
"""

import pytest

from ideology_app.feedback.message import (
    CONTROL_CHARACTER,
    EMPTY,
    MAX_CHARS,
    TOO_LONG,
    TRIM_CHARS,
    clean_message,
)

# (input, expected): a str is the stored text; otherwise the problem.
VECTORS: list[tuple[str, str]] = [
    ("x" * 500, "x" * 500),
    ("😀" * 500, "😀" * 500),
    ("x" * 500 + "  \n", "x" * 500),
    ("x" * 501, "too_long"),
    ("😀" * 501, "too_long"),
    ("", "empty"),
    ("   ", "empty"),
    ("\n\n", "empty"),
    (" \u3000\ufeff hola  ", "hola"),
    ("a\nb", "a\nb"),
    ("a\tb", "control_character"),
    ("a\r\nb", "control_character"),
    ("a\u0000", "control_character"),
    ("a\u0085", "control_character"),
    ("a\u001b[31m", "control_character"),
    ("\ud800", "control_character"),
    ("e\u0301", "e\u0301"),
]

PROBLEMS = {"control_character": CONTROL_CHARACTER, "empty": EMPTY, "too_long": TOO_LONG}


@pytest.mark.parametrize(("raw", "expected"), VECTORS, ids=[repr(v[0])[:24] for v in VECTORS])
def test_shared_vectors(raw: str, expected: str) -> None:
    if expected in PROBLEMS:
        with pytest.raises(ValueError) as info:
            clean_message(raw)
        assert str(info.value) == PROBLEMS[expected]
    else:
        assert clean_message(raw) == expected


def test_counts_code_points_without_normalisation() -> None:
    assert len(clean_message("e\u0301")) == 2
    assert len("😀" * 500) == MAX_CHARS  # 1000 UTF-16 units, 500 code points


def test_trim_set_is_ecmascript_not_python() -> None:
    # Python's bare strip() would remove these, JS trim() keeps them; they are
    # refused as controls anyway, so trimming never reaches them.
    for char in ("\u001c", "\u001d", "\u001e", "\u001f", "\u0085"):
        assert char not in TRIM_CHARS
    # JS trim() removes U+FEFF; Python's strip() does not.
    assert "\ufeff" in TRIM_CHARS
    assert clean_message("\ufeffhola\ufeff") == "hola"
    for char in "\u00a0\u1680\u2000\u200a\u2028\u2029\u202f\u205f\u3000":
        assert clean_message(f"{char}x{char}") == "x"


def test_inner_whitespace_and_zero_width_joiner_are_kept() -> None:
    assert clean_message("  a  b  ") == "a  b"
    family = "👨\u200d👩\u200d👧"
    assert clean_message(family) == family


def test_control_check_runs_on_the_raw_value_before_trim() -> None:
    with pytest.raises(ValueError, match="control"):
        clean_message("hola\t")
    with pytest.raises(ValueError, match="control"):
        clean_message("\rhola")
    for char in ("\u007f", "\u009f", "\u0080"):
        with pytest.raises(ValueError, match="control"):
            clean_message(f"a{char}")
