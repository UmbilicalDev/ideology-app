"""The 52 Congreso Constituencies (constituencies-and-candidatures, Scenario 1)."""

import importlib.util
from pathlib import Path

import sqlalchemy as sa
from click.testing import CliRunner
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from ideology_app.cli import main
from ideology_app.constituencies import CODES, CONSTITUENCIES, INE_SOURCE_URL, name_of
from ideology_app.elections import constituency_seed_problems

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "src/ideology_app/migrations/versions/0016_constituencies_candidatures.py"
)


def test_there_are_52_with_codes_01_to_52_in_order() -> None:
    codes = [code for code, _ in CONSTITUENCIES]
    assert len(CONSTITUENCIES) == 52
    assert codes == [f"{n:02d}" for n in range(1, 53)]
    assert len(set(codes)) == 52
    assert CODES == frozenset(codes)
    assert all(isinstance(code, str) and len(code) == 2 for code in codes)


def test_names_are_non_empty_and_unique() -> None:
    names = [name for _, name in CONSTITUENCIES]
    assert all(name and name == name.strip() for name in names)
    assert len(set(names)) == 52


def test_spot_checks() -> None:
    assert name_of("51") == "Ceuta"
    assert name_of("52") == "Melilla"
    assert name_of("28") == "Madrid"
    assert name_of("08") == "Barcelona"
    assert name_of("18") == "Granada"
    # D3: inverted INE articles moved to the front; bilingual names kept.
    assert name_of("15") == "A Coruña"
    assert name_of("07") == "Illes Balears"
    assert name_of("35") == "Las Palmas"
    assert name_of("26") == "La Rioja"
    assert name_of("01") == "Araba/Álava"
    assert name_of("46") == "Valencia/València"
    assert INE_SOURCE_URL.startswith("https://www.ine.es/")


def test_migration_literal_equals_the_module() -> None:
    spec = importlib.util.spec_from_file_location("migration_0016", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module._CONSTITUENCIES == CONSTITUENCIES


def test_seeded_table_equals_the_module(migrated_engine: Engine) -> None:
    with migrated_engine.connect() as conn:
        rows = [
            tuple(r)
            for r in conn.execute(sa.text("SELECT code, name FROM constituencies ORDER BY code"))
        ]
    assert rows == list(CONSTITUENCIES)
    with Session(migrated_engine) as session:
        assert constituency_seed_problems(session) == []


def test_seed_problems_name_each_difference(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as conn:
        conn.execute(sa.text("UPDATE constituencies SET name = 'Gerona' WHERE code = '17'"))
        conn.execute(sa.text("DELETE FROM constituencies WHERE code = '52'"))
        conn.execute(sa.text("INSERT INTO constituencies VALUES ('99', 'Extranjero')"))
    with Session(migrated_engine) as session:
        assert constituency_seed_problems(session) == [
            "Constituency 17 is named 'Gerona' in the constituencies table, not 'Girona'",
            "Constituency 52 (Melilla) is missing from the constituencies table",
            "Constituency 99 (Extranjero) in the constituencies table is not a Congreso "
            "Constituency",
        ]


def test_constituency_list_needs_no_database(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path}/never.db"
    result = CliRunner().invoke(main, ["--database-url", url, "constituency", "list"])
    assert result.exit_code == 0, result.output
    assert result.output == "".join(f"{code}\t{name}\n" for code, name in CONSTITUENCIES)
    assert not (tmp_path / "never.db").exists()
