"""The topic catalog (topic-catalog): names, citizen-priority order, CIS mapping, TS copy."""

import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select

from ideology_app import shared_db, topic_catalog
from ideology_app.models import Statement
from ideology_app.pipeline.prompts import TOPICS
from ideology_app.topic_catalog import (
    CIS_6R_TOTALS,
    CIS_6R_UNMAPPED,
    CIS_SOURCE,
    TOPIC_CATALOG,
    TopicEntry,
    catalog_problems,
    rank_order,
    render_typescript,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATED_TS = REPO_ROOT / "packages" / "core" / "src" / "domain" / "topic-catalog.generated.ts"
COMMITTED_DB = REPO_ROOT / "data" / "ideology.db"

# The spec's table: display order, key, Spanish name, rank value in tenths (None: no category).
EXPECTED = (
    ("housing", "Vivienda", 595),
    ("economy", "Economía", 247),
    ("employment", "Empleo", 239),
    ("immigration", "Inmigración", 231),
    ("democracy_institutions", "Democracia e instituciones", 132),
    ("health", "Sanidad", 127),
    ("social_rights_equality", "Derechos sociales e igualdad", 75),
    ("education", "Educación", 65),
    ("justice_security", "Justicia y seguridad", 55),
    ("environment_energy", "Medio ambiente y energía", 36),
    ("taxation", "Impuestos", 23),
    ("pensions", "Pensiones", 18),
    ("foreign_policy_defense", "Política exterior y defensa", 11),
    ("infrastructure_transport", "Infraestructuras y transporte", 11),
    ("science_digital", "Ciencia y digitalización", 7),
    ("territorial_model", "Modelo territorial", 4),
    ("agriculture_rural", "Agricultura y mundo rural", 4),
    ("culture_language", "Cultura y lenguas", None),
)


def _replace(index: int, **changes: object) -> list[TopicEntry]:
    entries = list(TOPIC_CATALOG)
    entries[index] = dataclasses.replace(entries[index], **changes)  # type: ignore[arg-type]
    return entries


# Scenario 1


def test_catalog_has_the_18_pipeline_keys_in_the_table_order() -> None:
    assert len(TOPIC_CATALOG) == 18
    assert sorted(e.key for e in TOPIC_CATALOG) == sorted(TOPICS)
    assert [e.order for e in TOPIC_CATALOG] == list(range(1, 19))
    assert [(e.key, e.name) for e in TOPIC_CATALOG] == [(k, n) for k, n, _ in EXPECTED]
    names = [e.name for e in TOPIC_CATALOG]
    assert all(n.strip() == n and n for n in names)
    assert len(set(names)) == 18


def test_cis_source_is_estudio_3587_question_6r() -> None:
    assert CIS_SOURCE.study == "3587"
    assert CIS_SOURCE.question == "6R"
    assert CIS_SOURCE.published == "2026-11-23"
    assert (CIS_SOURCE.fieldwork_start, CIS_SOURCE.fieldwork_end) == ("2026-11-10", "2026-11-17")
    assert CIS_SOURCE.sample == 8034


# Scenario 2


def test_real_catalog_has_no_problems() -> None:
    assert catalog_problems(TOPIC_CATALOG, TOPICS) == []


@pytest.mark.parametrize("blank", ["", "   "])
def test_empty_name_is_a_problem(blank: str) -> None:
    problems = catalog_problems(_replace(2, name=blank), TOPICS)
    assert problems == ["employment: empty name"]


def test_duplicate_name_is_a_problem() -> None:
    problems = catalog_problems(_replace(1, name="Vivienda"), TOPICS)
    assert problems == ["economy: name 'Vivienda' also used by housing"]


def test_duplicate_order_is_a_problem() -> None:
    # Order 4 is used twice, so order 5 is missing.
    problems = catalog_problems(_replace(4, order=4), TOPICS)
    assert problems == [
        "democracy_institutions: order 4 also used by immigration",
        "order 5 is used by no topic",
    ]


@pytest.mark.parametrize("order", [0, 19, -1])
def test_order_outside_the_range_is_a_problem(order: int) -> None:
    problems = catalog_problems(_replace(0, order=order), TOPICS)
    assert problems == [f"housing: order {order} outside 1..18", "order 1 is used by no topic"]


def test_missing_key_is_a_problem() -> None:
    entries = [e for e in TOPIC_CATALOG if e.key != "pensions"]
    problems = catalog_problems(entries, TOPICS)
    assert "pensions: missing from the catalog" in problems


def test_key_missing_from_the_pipeline_topics_is_a_problem() -> None:
    legacy = tuple(k for k in TOPICS if k != "taxation")
    assert catalog_problems(TOPIC_CATALOG, legacy) == ["taxation: not a pipeline topic key"]


def test_extra_key_is_a_problem() -> None:
    entries = [*TOPIC_CATALOG, TopicEntry("tourism", "Turismo", 19, ())]
    problems = catalog_problems(entries, TOPICS)
    assert "tourism: not a pipeline topic key" in problems


def test_duplicate_key_is_a_problem() -> None:
    problems = catalog_problems(_replace(1, key="housing"), TOPICS)
    assert "housing: duplicate key" in problems
    assert "economy: missing from the catalog" in problems


# Scenario 3


def test_cis_categories_are_the_55_published_ones() -> None:
    labels = [label for label, _ in CIS_6R_TOTALS]
    assert len(labels) == 55
    assert len(set(labels)) == 55
    assert all(isinstance(t, int) and t > 0 for _, t in CIS_6R_TOTALS)
    # Published order: TOTAL never increases.
    totals = [t for _, t in CIS_6R_TOTALS]
    assert totals == sorted(totals, reverse=True)
    assert all(" " * 2 not in label and label == label.strip() for label in labels)


def test_every_category_is_mapped_once_or_unmapped() -> None:
    recorded = {label for label, _ in CIS_6R_TOTALS}
    mapped = [label for e in TOPIC_CATALOG for label in e.cis_categories]
    assert len(mapped) == 49
    assert len(set(mapped)) == len(mapped)
    assert len(CIS_6R_UNMAPPED) == len(set(CIS_6R_UNMAPPED)) == 6
    assert set(mapped).isdisjoint(CIS_6R_UNMAPPED)
    assert set(mapped) | set(CIS_6R_UNMAPPED) == recorded


def test_rank_values_match_the_table() -> None:
    totals = dict(CIS_6R_TOTALS)
    for entry, (key, _, value) in zip(TOPIC_CATALOG, EXPECTED, strict=True):
        assert entry.key == key
        best = max((totals[c] for c in entry.cis_categories), default=None)
        assert best == value, key


def test_order_rule_gives_the_declared_order() -> None:
    declared = tuple(e.key for e in sorted(TOPIC_CATALOG, key=lambda e: e.order))
    assert rank_order(TOPIC_CATALOG, CIS_6R_TOTALS, TOPICS) == declared
    assert declared == tuple(k for k, _, _ in EXPECTED)


def test_order_rule_uses_the_highest_total_not_the_sum() -> None:
    # By sum, democracy_institutions (58,8) would come 2nd; by its highest TOTAL
    # (13,2) it comes 5th.
    totals = dict(CIS_6R_TOTALS)
    democracy = next(e for e in TOPIC_CATALOG if e.key == "democracy_institutions")
    assert sum(totals[c] for c in democracy.cis_categories) == 588
    assert max(totals[c] for c in democracy.cis_categories) == 132
    assert rank_order(TOPIC_CATALOG, CIS_6R_TOTALS, TOPICS).index("democracy_institutions") == 4


def test_order_rule_breaks_ties_and_places_uncategorised_topics_by_legacy_order() -> None:
    a = TopicEntry("a", "A", 1, ("x",))
    b = TopicEntry("b", "B", 2, ("y",))
    c = TopicEntry("c", "C", 3, ())
    d = TopicEntry("d", "D", 4, ())
    totals = (("x", 11), ("y", 11))
    assert rank_order([a, b, c, d], totals, ("d", "b", "c", "a")) == ("b", "a", "d", "c")


def test_order_rule_rejects_an_unknown_category() -> None:
    entries = _replace(0, cis_categories=("Una categoría que no existe",))
    with pytest.raises(KeyError):
        rank_order(entries, CIS_6R_TOTALS, TOPICS)


def test_module_does_not_import_the_pipeline() -> None:
    code = (
        "import sys, ideology_app.topic_catalog; "
        "sys.exit(1 if any(m.startswith('ideology_app.pipeline') for m in sys.modules) else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


# Scenario 4


def test_generated_typescript_matches_the_python_catalog() -> None:
    assert GENERATED_TS.is_file(), f"{GENERATED_TS} is missing"
    assert GENERATED_TS.read_text(encoding="utf-8") == render_typescript(), (
        "topic-catalog.generated.ts is stale; regenerate it with "
        "`.venv/bin/python -m ideology_app.topic_catalog > "
        "packages/core/src/domain/topic-catalog.generated.ts`"
    )


def test_rendered_typescript_lists_every_entry_in_order() -> None:
    text = render_typescript()
    assert "Do not edit" in text
    rows = [f'{{ key: "{e.key}", name: "{e.name}", order: {e.order} }}' for e in TOPIC_CATALOG]
    positions = [text.index(row) for row in rows]
    assert positions == sorted(positions)
    assert text.endswith('export type TopicKey = (typeof TOPIC_CATALOG)[number]["key"];\n')


def test_module_main_writes_the_typescript() -> None:
    out = subprocess.run(
        [sys.executable, "-m", topic_catalog.__name__],
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    assert out == render_typescript()


# Scenario 5


def test_every_committed_statement_topic_is_a_catalog_key() -> None:
    assert COMMITTED_DB.is_file(), f"{COMMITTED_DB} is missing"
    assert shared_db.file_checks(COMMITTED_DB) == []
    engine = create_engine(shared_db.read_only_url(COMMITTED_DB))
    try:
        with engine.connect() as conn:
            topics = set(conn.execute(select(Statement.topic).distinct()).scalars())
    finally:
        engine.dispose()
    assert topics
    assert topics <= {e.key for e in TOPIC_CATALOG}
