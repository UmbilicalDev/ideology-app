"""The 52 Congreso Constituencies (circunscripciones): INE province codes and names.

Pure (standard library only). ``CONSTITUENCIES`` is the reference list: the
migration ``0016_constituencies_candidatures`` seeds the ``constituencies``
table with its own literal copy, and ``elections.constituency_seed_problems``
plus the tests keep the two equal. Constituencies change only by migration.

Source: INE, "Relación de provincias con sus códigos" (``INE_SOURCE_URL``,
fetched 2026-11-24). Names are the INE official names, with an inverted article
moved to the front (``Coruña, A`` -> ``A Coruña``, ``Balears, Illes`` ->
``Illes Balears``, ``Palmas, Las`` -> ``Las Palmas``, ``Rioja, La`` ->
``La Rioja``). Bilingual names stay as INE writes them.
"""

INE_SOURCE_URL = "https://www.ine.es/daco/daco42/codmun/cod_provincia.htm"

CONSTITUENCIES: tuple[tuple[str, str], ...] = (
    ("01", "Araba/Álava"),
    ("02", "Albacete"),
    ("03", "Alicante/Alacant"),
    ("04", "Almería"),
    ("05", "Ávila"),
    ("06", "Badajoz"),
    ("07", "Illes Balears"),
    ("08", "Barcelona"),
    ("09", "Burgos"),
    ("10", "Cáceres"),
    ("11", "Cádiz"),
    ("12", "Castellón/Castelló"),
    ("13", "Ciudad Real"),
    ("14", "Córdoba"),
    ("15", "A Coruña"),
    ("16", "Cuenca"),
    ("17", "Girona"),
    ("18", "Granada"),
    ("19", "Guadalajara"),
    ("20", "Gipuzkoa"),
    ("21", "Huelva"),
    ("22", "Huesca"),
    ("23", "Jaén"),
    ("24", "León"),
    ("25", "Lleida"),
    ("26", "La Rioja"),
    ("27", "Lugo"),
    ("28", "Madrid"),
    ("29", "Málaga"),
    ("30", "Murcia"),
    ("31", "Navarra"),
    ("32", "Ourense"),
    ("33", "Asturias"),
    ("34", "Palencia"),
    ("35", "Las Palmas"),
    ("36", "Pontevedra"),
    ("37", "Salamanca"),
    ("38", "Santa Cruz de Tenerife"),
    ("39", "Cantabria"),
    ("40", "Segovia"),
    ("41", "Sevilla"),
    ("42", "Soria"),
    ("43", "Tarragona"),
    ("44", "Teruel"),
    ("45", "Toledo"),
    ("46", "Valencia/València"),
    ("47", "Valladolid"),
    ("48", "Bizkaia"),
    ("49", "Zamora"),
    ("50", "Zaragoza"),
    ("51", "Ceuta"),
    ("52", "Melilla"),
)

CODES: frozenset[str] = frozenset(code for code, _ in CONSTITUENCIES)
_NAMES: dict[str, str] = dict(CONSTITUENCIES)


def name_of(code: str) -> str:
    """The name of the Constituency ``code`` (e.g. ``"28"`` -> ``"Madrid"``). Raises KeyError."""
    return _NAMES[code]
