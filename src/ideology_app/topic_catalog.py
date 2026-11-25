"""The topic catalog: Spanish names and citizen-priority display order (topic-catalog).

The 18 topic keys are the ones of ``pipeline.prompts.Topic`` and never change
while a Dataset Version uses them. Each key gets a Spanish display name and a
1-based display order. The order follows CIS estudio 3587 (Barómetro de
noviembre 2026), Pregunta 6R, TOTAL column: a topic's rank value is the
highest TOTAL among the CIS categories mapped to it (not their sum). Ties, and
topics with no mapped category (placed last), keep the legacy ``TOPICS``
order, which is the prompt order and is not the display order.

This module is pure and imports nothing from ``pipeline``, so Proposal code
can use it. The web client reads the same catalog from the generated
``packages/core/src/domain/topic-catalog.generated.ts``; regenerate it with
``.venv/bin/python -m ideology_app.topic_catalog > packages/core/src/domain/topic-catalog.generated.ts``
and never edit it by hand (``tests/test_topic_catalog.py`` checks they match).
"""

import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class CisSource:
    study: str
    title: str
    published: str
    fieldwork_start: str
    fieldwork_end: str
    sample: int
    question: str
    question_text: str
    results_url: str
    advance_url: str


CIS_SOURCE = CisSource(
    study="3587",
    title="Barómetro de noviembre 2026",
    published="2026-11-23",
    fieldwork_start="2026-11-10",
    fieldwork_end="2026-11-17",
    sample=8034,
    question="6R",
    question_text=(
        "¿Cuál es, a su juicio, el principal problema que existe actualmente en España? "
        "¿Y el segundo? ¿Y el tercero?"
    ),
    results_url="https://www.cis.es/documents/d/guest/es3587mar_a-pdf",
    advance_url=(
        "https://www.cis.es/en/w/avance-de-resultados-del-estudio-3587-bar%C3%B3metro-de-noviembre-2026-"
    ),
)

# Pregunta 6R, every published category with its TOTAL (sum of the three
# mentions, % of respondents) in integer tenths of a percent (59,5 -> 595), in
# the published order. Labels as printed; a wrapped label is joined with one
# space. "Otras respuestas", "Ninguno", "N.S." and "N.C." are not categories.
CIS_6R_TOTALS: tuple[tuple[str, int], ...] = (
    ("La vivienda", 595),
    ("La crisis económica, los problemas de índole económica", 247),
    ("Los problemas relacionados con la calidad del empleo", 239),
    ("La inmigración", 231),
    ("Los problemas políticos en general", 132),
    ("La sanidad", 127),
    ("El Gobierno y partidos o políticos/as concretos/as", 124),
    ("El paro", 91),
    ("El mal comportamiento de los/as políticos/as", 88),
    ("Los extremismos", 80),
    ("La corrupción y el fraude", 76),
    (
        "Los problemas relacionados con la juventud. Falta de apoyo y oportunidades "
        "para los/as jóvenes",
        75,
    ),
    ("La educación", 65),
    ("La inseguridad ciudadana", 55),
    ("La crisis de valores", 49),
    ("Las desigualdades, incluida la de género, diferencias de clases, la pobreza", 46),
    ("Aumento de la crispación social, revueltas sociales", 43),
    ("Lo que hacen los partidos políticos", 37),
    ("El cambio climático", 36),
    ("El funcionamiento de los servicios públicos", 35),
    ("Los problemas de índole social", 27),
    ("La subida de los impuestos", 23),
    (
        "Papel de los medios de comunicación y redes: desinformación, manipulación "
        "informativa, difusión de bulos",
        19,
    ),
    ("Las pensiones", 18),
    ("El funcionamiento de la democracia", 13),
    (
        "Política exterior y relaciones internacionales. Papel de España en el marco "
        "internacional",
        11,
    ),
    ("Las infraestructuras", 11),
    ("Los problemas relacionados con el agua, la sequía", 11),
    ("La Administración de Justicia", 11),
    ("El racismo", 10),
    ("Las guerras en general", 9),
    ("La falta de confianza en los/las políticos/as y las instituciones", 9),
    ("La subida de tarifas energéticas, crisis energética", 9),
    (
        "La falta de acuerdos, unidad y capacidad de colaboración. Situación e "
        "inestabilidad política",
        8,
    ),
    ("El modelo productivo español. La falta de inversión en industrias e I+D", 7),
    ("La violencia de género", 7),
    ("El medio ambiente", 7),
    ("Las incertidumbres ante el futuro, la inseguridad y el miedo al futuro", 7),
    ("Crisis con Marruecos. Fronteras de Ceuta y Melilla", 5),
    ("Los problemas relacionados con los/as autónomos/as", 5),
    ("Los problemas de la agricultura, ganadería y pesca", 4),
    ("Poca conciencia ciudadana (falta de civismo, de sentido espíritu cívico)", 4),
    ("La ocupación de viviendas", 4),
    ("Los nacionalismos", 4),
    ("La falta de servicios públicos. Los recortes", 3),
    ("Los problemas relacionados con la mujer", 3),
    ("Los estatutos de autonomía", 3),
    ("Los problemas derivados del turismo. Masificación", 3),
    ("Preocupación sobre la salud propia, de familiares y/o allegados/as", 3),
    ("Problemas psicológicos (preocupaciones, soledad, tristeza, desamparo, etc.)", 2),
    ("La España vaciada, la despoblación", 2),
    ("La Monarquía", 2),
    ("La independencia de Cataluña", 2),
    ("Las drogas", 2),
    ("Los incendios", 1),
)

# Categories that are a general mood or cut across many areas rather than
# being one policy area, so they rank no topic.
CIS_6R_UNMAPPED: tuple[str, ...] = (
    "La crisis de valores",
    "Aumento de la crispación social, revueltas sociales",
    "El funcionamiento de los servicios públicos",
    "Las incertidumbres ante el futuro, la inseguridad y el miedo al futuro",
    "Poca conciencia ciudadana (falta de civismo, de sentido espíritu cívico)",
    "La falta de servicios públicos. Los recortes",
)


@dataclass(frozen=True)
class TopicEntry:
    key: str
    name: str
    order: int
    cis_categories: tuple[str, ...]


# In display order.
TOPIC_CATALOG: tuple[TopicEntry, ...] = (
    TopicEntry("housing", "Vivienda", 1, ("La vivienda",)),
    TopicEntry(
        "economy",
        "Economía",
        2,
        (
            "La crisis económica, los problemas de índole económica",
            "Los problemas derivados del turismo. Masificación",
        ),
    ),
    TopicEntry(
        "employment",
        "Empleo",
        3,
        (
            "Los problemas relacionados con la calidad del empleo",
            "El paro",
            "Los problemas relacionados con los/as autónomos/as",
        ),
    ),
    TopicEntry("immigration", "Inmigración", 4, ("La inmigración",)),
    TopicEntry(
        "democracy_institutions",
        "Democracia e instituciones",
        5,
        (
            "Los problemas políticos en general",
            "El Gobierno y partidos o políticos/as concretos/as",
            "El mal comportamiento de los/as políticos/as",
            "Los extremismos",
            "La corrupción y el fraude",
            "Lo que hacen los partidos políticos",
            "Papel de los medios de comunicación y redes: desinformación, manipulación "
            "informativa, difusión de bulos",
            "El funcionamiento de la democracia",
            "La falta de confianza en los/las políticos/as y las instituciones",
            "La falta de acuerdos, unidad y capacidad de colaboración. Situación e "
            "inestabilidad política",
            "La Monarquía",
        ),
    ),
    TopicEntry(
        "health",
        "Sanidad",
        6,
        (
            "La sanidad",
            "Preocupación sobre la salud propia, de familiares y/o allegados/as",
            "Problemas psicológicos (preocupaciones, soledad, tristeza, desamparo, etc.)",
            "Las drogas",
        ),
    ),
    TopicEntry(
        "social_rights_equality",
        "Derechos sociales e igualdad",
        7,
        (
            "Los problemas relacionados con la juventud. Falta de apoyo y oportunidades "
            "para los/as jóvenes",
            "Las desigualdades, incluida la de género, diferencias de clases, la pobreza",
            "Los problemas de índole social",
            "El racismo",
            "La violencia de género",
            "Los problemas relacionados con la mujer",
        ),
    ),
    TopicEntry("education", "Educación", 8, ("La educación",)),
    TopicEntry(
        "justice_security",
        "Justicia y seguridad",
        9,
        (
            "La inseguridad ciudadana",
            "La Administración de Justicia",
            "La ocupación de viviendas",
        ),
    ),
    TopicEntry(
        "environment_energy",
        "Medio ambiente y energía",
        10,
        (
            "El cambio climático",
            "Los problemas relacionados con el agua, la sequía",
            "La subida de tarifas energéticas, crisis energética",
            "El medio ambiente",
            "Los incendios",
        ),
    ),
    TopicEntry("taxation", "Impuestos", 11, ("La subida de los impuestos",)),
    TopicEntry("pensions", "Pensiones", 12, ("Las pensiones",)),
    TopicEntry(
        "foreign_policy_defense",
        "Política exterior y defensa",
        13,
        (
            "Política exterior y relaciones internacionales. Papel de España en el marco "
            "internacional",
            "Las guerras en general",
            "Crisis con Marruecos. Fronteras de Ceuta y Melilla",
        ),
    ),
    TopicEntry(
        "infrastructure_transport",
        "Infraestructuras y transporte",
        14,
        ("Las infraestructuras",),
    ),
    TopicEntry(
        "science_digital",
        "Ciencia y digitalización",
        15,
        ("El modelo productivo español. La falta de inversión en industrias e I+D",),
    ),
    TopicEntry(
        "territorial_model",
        "Modelo territorial",
        16,
        (
            "Los nacionalismos",
            "Los estatutos de autonomía",
            "La independencia de Cataluña",
        ),
    ),
    TopicEntry(
        "agriculture_rural",
        "Agricultura y mundo rural",
        17,
        (
            "Los problemas de la agricultura, ganadería y pesca",
            "La España vaciada, la despoblación",
        ),
    ),
    TopicEntry("culture_language", "Cultura y lenguas", 18, ()),
)


def rank_order(
    entries: Sequence[TopicEntry],
    totals: Sequence[tuple[str, int]],
    legacy_order: Sequence[str],
) -> tuple[str, ...]:
    """Keys sorted by the order rule.

    Rank value: the highest TOTAL (tenths) among a topic's categories. Highest
    first; ties by ``legacy_order``; topics with no category last, also by
    ``legacy_order``. A category missing from ``totals`` raises ``KeyError``.
    """
    by_label = dict(totals)
    legacy_index = {key: i for i, key in enumerate(legacy_order)}

    def sort_key(entry: TopicEntry) -> tuple[int, int, int]:
        index = legacy_index[entry.key]
        if not entry.cis_categories:
            return (1, 0, index)
        best = max(by_label[label] for label in entry.cis_categories)
        return (0, -best, index)

    return tuple(entry.key for entry in sorted(entries, key=sort_key))


def catalog_problems(entries: Sequence[TopicEntry], legacy_keys: Sequence[str]) -> list[str]:
    """What is wrong with ``entries`` (empty when nothing is)."""
    problems: list[str] = []
    seen_keys: set[str] = set()
    seen_names: dict[str, str] = {}
    seen_orders: dict[int, str] = {}
    for entry in entries:
        if entry.key in seen_keys:
            problems.append(f"{entry.key}: duplicate key")
        seen_keys.add(entry.key)
        name = entry.name.strip()
        if not name:
            problems.append(f"{entry.key}: empty name")
        elif name in seen_names:
            problems.append(f"{entry.key}: name {name!r} also used by {seen_names[name]}")
        else:
            seen_names[name] = entry.key
        if entry.order in seen_orders:
            problems.append(
                f"{entry.key}: order {entry.order} also used by {seen_orders[entry.order]}"
            )
        else:
            seen_orders[entry.order] = entry.key
        if not 1 <= entry.order <= len(entries):
            problems.append(f"{entry.key}: order {entry.order} outside 1..{len(entries)}")
        if entry.key not in legacy_keys:
            problems.append(f"{entry.key}: not a pipeline topic key")
    for order in range(1, len(entries) + 1):
        if order not in seen_orders:
            problems.append(f"order {order} is used by no topic")
    for key in legacy_keys:
        if key not in seen_keys:
            problems.append(f"{key}: missing from the catalog")
    return problems


def render_typescript() -> str:
    """The content of ``packages/core/src/domain/topic-catalog.generated.ts``."""
    lines = [
        "// Generated by `python -m ideology_app.topic_catalog` from",
        "// src/ideology_app/topic_catalog.py. Do not edit: change the Python module",
        "// and regenerate (tests/test_topic_catalog.py checks they match).",
        "export const TOPIC_CATALOG = [",
    ]
    for entry in sorted(TOPIC_CATALOG, key=lambda e: e.order):
        key = json.dumps(entry.key, ensure_ascii=False)
        name = json.dumps(entry.name, ensure_ascii=False)
        lines.append(f"  {{ key: {key}, name: {name}, order: {entry.order} }},")
    lines.append("] as const;")
    lines.append("")
    lines.append('export type TopicKey = (typeof TOPIC_CATALOG)[number]["key"];')
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.stdout.write(render_typescript())
