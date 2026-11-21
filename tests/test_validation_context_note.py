"""Check ``context_note`` and its settings (pipeline-statement-clarity-context).

Scenario 8 (the check) and scenario 11 (configuration). Pure data: no database,
no LLM.
"""

from collections.abc import Sequence
from dataclasses import replace

import pytest
from pipeline_fixtures import offline_guard

from ideology_app.config import (
    CONTEXT_NOTE_MAX_CHARS_LIMIT,
    DEFAULT_CONTEXT_NOTE_EVALUATIVE_WORDS,
    DEFAULT_CONTEXT_NOTE_MAX_CHARS,
    DEFAULT_CONTEXT_NOTE_MIN_CHARS,
    ConfigError,
    ValidationSettings,
    validation_settings,
)
from ideology_app.validation import (
    CHECKS,
    CONTEXT_NOTE,
    ReportEntry,
    StatementRow,
    ValidationInput,
)
from ideology_app.validation.context_note import (
    check_context_note,
    evaluative_matches,
    note_words,
)

VALID = "La Ley de Vivienda de 2023 regula el alquiler y las ayudas a la vivienda."


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    offline_guard(monkeypatch)


def data(
    notes: Sequence[str | None], settings: ValidationSettings | None = None
) -> ValidationInput:
    """Statements at positions 1..n with ids 101.., one per note."""
    return ValidationInput(
        statements=tuple(
            StatementRow(
                id=100 + n,
                position=n,
                text=f"Afirmación {n}.",
                topic="housing",
                context_note=note,
            )
            for n, note in enumerate(notes, start=1)
        ),
        positions=(),
        party_ids=(1, 2),
        settings=settings or ValidationSettings(),
    )


def messages(notes: Sequence[str | None], settings: ValidationSettings | None = None) -> list[str]:
    return [e.message for e in check_context_note(data(notes, settings))]


def test_registered_last_in_checks() -> None:
    assert CHECKS[-1] is CONTEXT_NOTE
    assert CONTEXT_NOTE.name == "context_note"
    assert CONTEXT_NOTE.run is check_context_note


def test_valid_notes_pass() -> None:
    assert check_context_note(data([VALID, VALID])) == []


@pytest.mark.parametrize("note", [None, "", "   ", " \n\t "])
def test_missing_or_blank_note(note: str | None) -> None:
    assert check_context_note(data([VALID, note])) == [
        ReportEntry("statement 2 has no context note", statement_id=102)
    ]


@pytest.mark.parametrize(
    ("length", "passes"), [(29, False), (30, True), (300, True), (301, False)]
)
def test_length_bounds_after_trimming(length: int, passes: bool) -> None:
    note = "  " + "a" * length + " \n"
    got = messages([note])
    if passes:
        assert got == []
    else:
        assert got == [f"statement 1 context note has {length} characters; expected 30 to 300"]


def test_length_bounds_come_from_settings() -> None:
    settings = replace(ValidationSettings(), context_note_min_chars=5, context_note_max_chars=10)
    assert messages(["a" * 5, "a" * 10], settings) == []
    assert messages(["a" * 11], settings) == [
        "statement 1 context note has 11 characters; expected 5 to 10"
    ]


@pytest.mark.parametrize(
    "note",
    [
        "Polémica e injustas: " + VALID,
        "POLEMICA, INJUSTAS. " + VALID,
        "polémica—injustas " + VALID,
        "Una polémica medida e injustas. " + VALID,  # decomposed accent
    ],
)
def test_evaluative_words_any_case_or_accents(note: str) -> None:
    # Matched entries are listed in word-list order (injustas comes before polémica).
    assert messages([note]) == [
        "statement 1 context note uses evaluative wording: injustas, polemica"
    ]


def test_matched_entries_follow_the_list_order_once_each() -> None:
    note = "Injustas, injustas y polémica; injusto. " + VALID
    assert messages([note]) == [
        "statement 1 context note uses evaluative wording: injusto, injustas, polemica"
    ]


@pytest.mark.parametrize(
    "note",
    [
        "La justicia es el poder del Estado que juzga y hace ejecutar lo juzgado.",
        "Se aplicó injustamente según algunos; el término no está en la lista de palabras.",
        "La palabra necesariamente no es una entrada de la lista de palabras valorativas.",
    ],
)
def test_whole_words_only(note: str) -> None:
    assert messages([note]) == []


def test_multi_word_entry_matches_only_consecutive_words() -> None:
    assert messages(["Por desgracia, la norma se aprobó en 2015 tras un largo debate."]) == [
        "statement 1 context note uses evaluative wording: por desgracia"
    ]
    assert messages(["Por la desgracia ocurrida, la norma se aprobó en 2015 tras un debate."]) == []
    assert evaluative_matches("por  \n desgracia", ("por desgracia",)) == ["por desgracia"]


def test_length_and_words_give_two_entries_for_one_statement() -> None:
    assert check_context_note(data(["Nefasta."])) == [
        ReportEntry(
            "statement 1 context note has 8 characters; expected 30 to 300", statement_id=101
        ),
        ReportEntry(
            "statement 1 context note uses evaluative wording: nefasta", statement_id=101
        ),
    ]


def test_entries_are_in_statement_order() -> None:
    got = messages([None, VALID, "corta", "Excelente: " + VALID])
    assert got == [
        "statement 1 has no context note",
        "statement 3 context note has 5 characters; expected 30 to 300",
        "statement 4 context note uses evaluative wording: excelente",
    ]


def test_word_list_comes_from_settings() -> None:
    settings = replace(ValidationSettings(), context_note_evaluative_words=("Ley Mordaza",))
    note = "La llamada ley mordaza es la Ley Orgánica 4/2015 de protección de la seguridad."
    assert messages([note], settings) == [
        "statement 1 context note uses evaluative wording: ley mordaza"
    ]
    assert messages(["Polémica: " + VALID], settings) == []


def test_note_words_folds_case_and_accents() -> None:
    assert note_words("¡Erróneo, CIE-2!") == ("erroneo", "cie", "2")


def test_the_check_is_pure() -> None:
    sample = data([None, "Polémica " + VALID])
    first = check_context_note(sample)
    assert check_context_note(sample) == first
    assert sample.statements[1].context_note == "Polémica " + VALID


# Scenario 11: settings and configuration.


def test_settings_defaults() -> None:
    settings = ValidationSettings()
    assert (settings.context_note_min_chars, settings.context_note_max_chars) == (30, 300)
    assert (DEFAULT_CONTEXT_NOTE_MIN_CHARS, DEFAULT_CONTEXT_NOTE_MAX_CHARS) == (30, 300)
    assert CONTEXT_NOTE_MAX_CHARS_LIMIT == 500
    assert settings.context_note_evaluative_words == DEFAULT_CONTEXT_NOTE_EVALUATIVE_WORDS
    words = DEFAULT_CONTEXT_NOTE_EVALUATIVE_WORDS
    assert len(words) == 69 and len(set(words)) == 69
    assert words[:4] == ("injusto", "injusta", "injustos", "injustas")
    assert words[-2:] == ("por desgracia", "por suerte")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"context_note_min_chars": 0},
        {"context_note_max_chars": 501},
        {"context_note_min_chars": 301},
        {"context_note_min_chars": 30.0},
        {"context_note_max_chars": True},
        {"context_note_evaluative_words": ()},
        {"context_note_evaluative_words": ["injusto"]},
        {"context_note_evaluative_words": ("injusto", "...")},
        {"context_note_evaluative_words": ("injusto", 3)},
    ],
)
def test_settings_reject(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ValidationSettings(**kwargs)  # type: ignore[arg-type]


def test_env_unset_gives_defaults() -> None:
    settings = validation_settings()
    assert settings.context_note_min_chars == 30
    assert settings.context_note_max_chars == 300
    assert settings.context_note_evaluative_words == DEFAULT_CONTEXT_NOTE_EVALUATIVE_WORDS


def test_env_values_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VALIDATION_CONTEXT_NOTE_MIN_CHARS", " 1 ")
    monkeypatch.setenv("VALIDATION_CONTEXT_NOTE_MAX_CHARS", "500")
    monkeypatch.setenv(
        "VALIDATION_CONTEXT_NOTE_EVALUATIVE_WORDS", " injusto , por desgracia,, Polémica "
    )
    settings = validation_settings()
    assert (settings.context_note_min_chars, settings.context_note_max_chars) == (1, 500)
    assert settings.context_note_evaluative_words == ("injusto", "por desgracia", "Polémica")


@pytest.mark.parametrize("raw", ["", "   "])
def test_blank_word_list_means_the_default(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("VALIDATION_CONTEXT_NOTE_EVALUATIVE_WORDS", raw)
    assert validation_settings().context_note_evaluative_words == (
        DEFAULT_CONTEXT_NOTE_EVALUATIVE_WORDS
    )


@pytest.mark.parametrize(
    "name", ["VALIDATION_CONTEXT_NOTE_MIN_CHARS", "VALIDATION_CONTEXT_NOTE_MAX_CHARS"]
)
@pytest.mark.parametrize("raw", ["0", "501", "-1", "+30", "30.5", "abc", "٣٠"])
def test_invalid_length_env_raises(monkeypatch: pytest.MonkeyPatch, name: str, raw: str) -> None:
    monkeypatch.setenv(name, raw)
    with pytest.raises(ConfigError) as info:
        validation_settings()
    assert str(info.value) == f"Invalid {name} {raw!r}; expected an integer from 1 to 500"


def test_min_above_max_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VALIDATION_CONTEXT_NOTE_MIN_CHARS", "301")
    with pytest.raises(ConfigError) as info:
        validation_settings()
    assert str(info.value) == (
        "Invalid context note length range: VALIDATION_CONTEXT_NOTE_MIN_CHARS (301) is "
        "greater than VALIDATION_CONTEXT_NOTE_MAX_CHARS (300)"
    )


@pytest.mark.parametrize("raw", [",", " , ,", "injusto, ..."])
def test_invalid_word_list_raises(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("VALIDATION_CONTEXT_NOTE_EVALUATIVE_WORDS", raw)
    with pytest.raises(ConfigError, match="^Invalid VALIDATION_CONTEXT_NOTE_EVALUATIVE_WORDS"):
        validation_settings()
