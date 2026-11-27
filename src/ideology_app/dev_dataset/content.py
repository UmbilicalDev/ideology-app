"""The fictional content of the dev dataset (dev-dataset, D1, D8).

Everything the seed renders and the scripted provider answers comes from
here: the Election, the Parties (named after minerals, invented), their
documents (pages of prose with verbatim measures), the Statement Pool with
Context Notes, the stances of each measure, the two scripted contradictions,
the Operator decision and the rewording. Nothing here names a real party.

Measures are written per document from the stance table: a document's lead-in
(e.g. ``Proponemos``) plus the Statement's ``pro`` or ``con`` action, so the
same action never gives the same text in two documents. A few measures carry
their own text (``_OVERRIDES``) and some carry no stance (``_EXTRAS``).

Pool shape (see ``docs/specs/dev-dataset.md``, Dataset Content):

- group A splits CUARZO and ONIX (valid wherever both run, Ceuta included);
- group B is split only by JADE or ZAFIRO;
- group C has the four national Parties on one side and BASALTO on the other;
- group D depends on ``turquesa.md`` (Galicia);
- ``cercanias-gestion`` (A) is the decided ONIX-CAT contradiction and
  ``redes-edad`` (B) the joint-manifesto contradiction of TURQUESA.

``check()`` returns the content problems (S7); it is pure.
"""

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ideology_app.constituencies import CONSTITUENCIES
from ideology_app.config import DEFAULT_CONTEXT_NOTE_EVALUATIVE_WORDS
from ideology_app.config import DEFAULT_CONTEXT_NOTE_MAX_CHARS, DEFAULT_CONTEXT_NOTE_MIN_CHARS
from ideology_app.proposals.extraction import PROPOSAL_CHUNK_MAX_CHARS, build_chunks
from ideology_app.topic_catalog import TOPIC_CATALOG
from ideology_app.validation.context_note import evaluative_matches
from ideology_app.validation.evidence_quotes import normalize_for_match

COUNTRY = "ES"
ELECTION_TYPE = "general"
ELECTION_DATE = dt.date(2031, 5, 18)
ELECTION_NAME = "Elecciones generales ficticias (datos de desarrollo)"
SLUG = f"{COUNTRY.lower()}-{ELECTION_TYPE}-{ELECTION_DATE.isoformat()}"
CANDIDATURES_SOURCE = "Candidaturas ficticias del conjunto de datos de desarrollo"
EXTRACTOR = "dev-dataset 1"
URL_BASE = "https://example.org/ideologiapp-dev/"

ALL = "all"
GALICIA = ("15", "27", "32", "36")
CATALONIA = ("08", "17", "25", "43")


# INE code order (``constituencies.CODES`` is a set: never iterate it here).
CODES: tuple[str, ...] = tuple(code for code, _ in CONSTITUENCIES)


def _all_except(*codes: str) -> tuple[str, ...]:
    return tuple(code for code in CODES if code not in codes)


@dataclass(frozen=True)
class DevParty:
    """A candidature: short name, name, Constituencies (``"all"`` or codes) and logo colour."""

    short_name: str
    name: str
    constituencies: str | tuple[str, ...]
    # Background colour of the generated logo, or None for no logo.
    logo_colour: str | None

    @property
    def logo_file(self) -> str | None:
        return None if self.logo_colour is None else f"logos/{self.short_name.lower()}.svg"

    def codes(self) -> tuple[str, ...]:
        return tuple(CODES) if self.constituencies == ALL else tuple(self.constituencies)


PARTIES: tuple[DevParty, ...] = (
    DevParty("CUARZO", "Partido Cuarzo", ALL, "#5b6c8f"),
    DevParty("JADE", "Movimiento Jade", _all_except(*GALICIA, "51", "52"), "#4f7a65"),
    DevParty("ONIX", "Unión Ónix", _all_except(*CATALONIA, "52"), "#4a4a57"),
    DevParty("ONIX-CAT", "Ònix Catalunya", CATALONIA, "#6b5a7a"),
    DevParty("ZAFIRO", "Confederación Zafiro", _all_except("51", "52"), None),
    DevParty("TURQUESA", "Coalición Turquesa", GALICIA, "#3f7f86"),
    DevParty("BASALTO", "Bloque Basalto", ("08",), "#6e6259"),
    DevParty("MICA", "Partido Mica", ("28",), "#8a7d5c"),
    DevParty("GRAFITO", "Agrupación Grafito", ("51", "52"), "#5f6466"),
    DevParty("PIZARRA", "Candidatura Pizarra", ("52",), "#56606e"),
)

GRAFITO_NOTE = "La candidatura no ha publicado programa electoral en el plazo de revisión."
PIZARRA_NOTE = "El documento solo contiene el índice del programa, sin medidas."


@dataclass(frozen=True)
class DevStatement:
    """A scripted Statement: key, main category, text, Context Note and the two actions
    a measure for (``pro``) or against (``con``) it proposes."""

    key: str
    category: str
    group: str
    text: str
    note: str
    pro: str
    con: str
    tag: str


@dataclass(frozen=True)
class DevMeasure:
    """A verbatim measure of a document: text, main category, tags and its stances."""

    text: str
    category: str
    tags: tuple[str, ...]
    stances: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class DevPage:
    """One page of a document: its full text and the measures printed on it."""

    number: int
    text: str
    measures: tuple[DevMeasure, ...] = ()


@dataclass(frozen=True)
class DevDocument:
    """A Source Text file: its front-matter Party, the Parties it is listed for and pages."""

    file: str
    party: str
    parties: tuple[str, ...]
    pages: tuple[DevPage, ...]
    source_url: str | None = None
    joint_for: tuple[str, ...] = ()

    @property
    def measures(self) -> tuple[DevMeasure, ...]:
        return tuple(m for page in self.pages for m in page.measures)

    def page_texts(self) -> list[str]:
        return [page.text for page in self.pages]


@dataclass(frozen=True)
class DevConflict:
    """A scripted contradiction between two measures of one Party's overlapping documents."""

    party: str
    files: tuple[str, str]
    texts: tuple[str, str]
    category: str
    explanation: str


@dataclass(frozen=True)
class DevDecision:
    """The Operator's decision on a pending overlap."""

    party: str
    prevails: str
    over: str
    reason: str


@dataclass(frozen=True)
class DevRewording:
    """The Operator's rewording of one Statement and the scripted equivalence verdict."""

    statement: str
    text: str
    reason: str
    explanation: str


# --- Statements ---------------------------------------------------------------------

_S = DevStatement

STATEMENTS: tuple[DevStatement, ...] = (
    # Vivienda
    _S("alquiler-limite", "housing", "A",
       "Debe limitarse por ley el precio del alquiler en las zonas con más demanda.",
       "Un límite al alquiler fija un precio máximo para los contratos nuevos o renovados en "
       "las zonas que la administración declara tensionadas por su demanda de vivienda.",
       "limitar por ley el precio del alquiler en las zonas declaradas tensionadas",
       "retirar los topes al precio del alquiler para que lo fije el acuerdo entre las partes",
       "alquiler"),
    _S("vivienda-publica", "housing", "B",
       "Debe aumentar el parque público de vivienda en alquiler social.",
       "El parque público de vivienda son las viviendas propiedad de las administraciones que "
       "se alquilan por debajo del precio de mercado a hogares con ingresos limitados.",
       "construir cien mil viviendas públicas para alquiler social en cinco años",
       "dedicar el suelo público a vivienda en venta a precio libre en lugar de alquiler social",
       "vivienda pública"),
    _S("aval-hipoteca", "housing", "B",
       "El Estado debe avalar parte de la hipoteca de quienes compran su primera vivienda.",
       "Un aval público garantiza al banco una parte del préstamo hipotecario, de modo que el "
       "comprador necesita aportar menos ahorro inicial.",
       "avalar con fondos públicos hasta el veinte por ciento de la hipoteca de la primera "
       "vivienda",
       "dejar de avalar con fondos públicos las hipotecas de particulares",
       "hipotecas"),
    _S("pisos-turisticos", "housing", "B",
       "Los ayuntamientos deben poder prohibir nuevos pisos turísticos en sus barrios.",
       "Los pisos turísticos son viviendas que se alquilan por días a visitantes; necesitan una "
       "licencia o un registro que gestionan comunidades autónomas y ayuntamientos.",
       "permitir a los ayuntamientos prohibir nuevas licencias de pisos turísticos en barrios "
       "saturados",
       "garantizar el derecho de los propietarios a alquilar su vivienda a turistas sin cupos "
       "municipales",
       "pisos turísticos"),
    # Economía
    _S("salario-minimo", "economy", "A",
       "El salario mínimo debe subir cada año hasta llegar al 60 % del salario medio.",
       "El salario mínimo interprofesional es la retribución más baja que la ley permite pagar "
       "por una jornada completa; el Gobierno lo fija cada año.",
       "subir el salario mínimo cada año hasta alcanzar el sesenta por ciento del salario medio",
       "congelar el salario mínimo hasta que mejore la productividad",
       "salario mínimo"),
    _S("banca-publica", "economy", "B",
       "Debe crearse una banca pública estatal.",
       "Una banca pública es una entidad financiera propiedad del Estado que concede préstamos "
       "y gestiona depósitos como un banco comercial.",
       "crear una banca pública estatal a partir de las entidades financieras participadas por "
       "el Estado",
       "vender las participaciones del Estado en entidades financieras",
       "banca pública"),
    _S("cuota-autonomos", "economy", "B",
       "Los autónomos con ingresos bajos deben dejar de pagar cuota a la Seguridad Social.",
       "Los autónomos son trabajadores por cuenta propia; pagan cada mes una cuota a la "
       "Seguridad Social que depende de sus rendimientos netos.",
       "eximir de la cuota de autónomos a quienes ganen menos del salario mínimo",
       "mantener una cuota mínima de autónomos para todos los trabajadores por cuenta propia",
       "autónomos"),
    # Empleo
    _S("jornada-35", "employment", "A",
       "La jornada laboral máxima debe bajar a 35 horas semanales.",
       "La jornada máxima legal es el número de horas de trabajo ordinario por semana que fija "
       "el Estatuto de los Trabajadores para todos los sectores.",
       "reducir la jornada laboral máxima a treinta y cinco horas semanales sin rebaja de sueldo",
       "mantener la jornada máxima en cuarenta horas y dejar su reducción a los convenios",
       "jornada laboral"),
    _S("despido-indemnizacion", "employment", "B",
       "La indemnización por despido improcedente debe aumentar.",
       "El despido improcedente es el que un juez declara sin causa justificada; la empresa "
       "debe readmitir a la persona o pagarle una indemnización fijada por ley.",
       "aumentar la indemnización por despido improcedente a cuarenta y cinco días por año "
       "trabajado",
       "mantener la indemnización por despido improcedente en su nivel actual",
       "despido"),
    _S("teletrabajo", "employment", "B",
       "Las empresas deben ofrecer teletrabajo en los puestos que lo permitan.",
       "El teletrabajo es el trabajo realizado a distancia, normalmente desde casa, con medios "
       "informáticos y en el horario pactado con la empresa.",
       "reconocer el derecho a teletrabajar dos días por semana en los puestos que lo permitan",
       "dejar el teletrabajo a la negociación individual entre empresa y trabajador",
       "teletrabajo"),
    _S("paro-formacion", "employment", "B",
       "El cobro de la prestación por desempleo debe ir unido a seguir una formación.",
       "La prestación por desempleo es la ayuda mensual que recibe quien ha perdido su empleo "
       "tras haber cotizado un tiempo mínimo a la Seguridad Social.",
       "condicionar la prestación por desempleo a seguir un curso de formación",
       "desvincular la prestación por desempleo de cualquier obligación de formación",
       "desempleo"),
    _S("salario-minimo-autonomico", "employment", "C",
       "Cada comunidad autónoma debe poder fijar su propio salario mínimo.",
       "Hoy el salario mínimo interprofesional es igual en todo el país; lo aprueba el Gobierno "
       "cada año tras consultar a sindicatos y organizaciones empresariales.",
       "permitir a cada comunidad autónoma fijar un salario mínimo propio",
       "mantener un salario mínimo único para todo el país",
       "salario mínimo"),
    # Sanidad
    _S("copago-pensionistas", "health", "A",
       "Los medicamentos con receta deben ser gratuitos para todos los pensionistas.",
       "El copago farmacéutico es la parte del precio de un medicamento con receta que paga el "
       "paciente; su porcentaje depende de la renta y de la situación laboral.",
       "eliminar el copago farmacéutico de todos los pensionistas",
       "mantener el copago farmacéutico de los pensionistas según su nivel de renta",
       "medicamentos"),
    _S("gestion-sanitaria-publica", "health", "A",
       "Los servicios sanitarios públicos deben prestarse solo en centros de gestión pública.",
       "Los conciertos sanitarios son contratos por los que la sanidad pública paga a centros "
       "privados para que atiendan a sus pacientes.",
       "prestar la atención sanitaria pública solo en centros de gestión pública",
       "ampliar los conciertos con clínicas privadas para reducir las listas de espera",
       "gestión sanitaria"),
    _S("plazo-operaciones", "health", "B",
       "Debe fijarse por ley un plazo máximo de espera para las operaciones programadas.",
       "La lista de espera quirúrgica es el registro de pacientes pendientes de una operación "
       "programada en la sanidad pública, con su tiempo de espera.",
       "fijar por ley un plazo máximo de noventa días para las operaciones programadas",
       "dejar los plazos de espera quirúrgica a la planificación de cada servicio de salud",
       "listas de espera"),
    _S("psicologos-primaria", "health", "B",
       "La sanidad pública debe incluir psicólogos en todos los centros de salud.",
       "Los centros de salud son los centros de atención primaria, la primera puerta de "
       "entrada a la sanidad pública para las consultas de medicina general.",
       "incorporar psicólogos clínicos en todos los centros de salud",
       "atender la salud mental en unidades especializadas de hospital y no en los centros de "
       "salud",
       "salud mental"),
    _S("dental-adultos", "health", "B",
       "La sanidad pública debe cubrir la atención dental de los adultos.",
       "Hoy la sanidad pública cubre sobre todo extracciones y atención dental infantil; la "
       "mayoría de los tratamientos de adultos se pagan en clínicas privadas.",
       "incluir los empastes y las prótesis dentales en la cartera de la sanidad pública",
       "ayudar con desgravaciones fiscales a quien pague tratamientos dentales privados",
       "salud dental"),
    # Educación
    _S("infantil-gratuita", "education", "A",
       "La educación infantil de cero a tres años debe ser gratuita.",
       "El primer ciclo de educación infantil atiende a niños de cero a tres años en escuelas "
       "infantiles; no es obligatorio y su coste varía entre comunidades.",
       "hacer gratuito el primer ciclo de educación infantil, de cero a tres años",
       "ayudar a las familias con cheques para la escuela infantil que elijan en lugar de "
       "hacerla gratuita",
       "educación infantil"),
    _S("conciertos-educativos", "education", "A",
       "Deben mantenerse los conciertos educativos con colegios privados.",
       "Los colegios concertados son centros de titularidad privada que reciben fondos públicos "
       "a cambio de impartir la enseñanza obligatoria de forma gratuita.",
       "mantener y ampliar los conciertos educativos con colegios de titularidad privada",
       "reducir de forma gradual los conciertos educativos con colegios privados",
       "enseñanza concertada"),
    _S("becas-renta", "education", "B",
       "Las becas universitarias deben depender solo de la renta familiar.",
       "Las becas de estudios son ayudas públicas para pagar la matrícula y otros gastos; hoy "
       "se conceden según la renta familiar y el rendimiento académico.",
       "conceder las becas universitarias solo según la renta familiar, sin nota mínima",
       "exigir una nota media mínima para conceder y renovar las becas universitarias",
       "becas"),
    _S("fp-dual", "education", "B",
       "La formación profesional debe hacerse en parte dentro de las empresas.",
       "La formación profesional dual combina las clases en el centro educativo con periodos de "
       "aprendizaje remunerado en una empresa.",
       "extender la formación profesional dual a todos los ciclos formativos",
       "mantener la formación profesional en los centros educativos con prácticas solo al "
       "final del ciclo",
       "formación profesional"),
    _S("ratio-aula", "education", "B",
       "El número máximo de alumnos por aula debe bajar a 20.",
       "La ratio es el número máximo de alumnos por grupo que fija la normativa educativa para "
       "cada etapa de la enseñanza.",
       "rebajar a veinte el número máximo de alumnos por aula en primaria y secundaria",
       "mantener las ratios actuales y destinar los fondos a refuerzo individual",
       "ratios"),
    _S("curriculo-autonomico", "education", "C",
       "El currículo escolar debe decidirse por completo en cada comunidad autónoma.",
       "El currículo fija los contenidos y objetivos de cada etapa educativa; hoy el Estado "
       "decide una parte común y las comunidades completan el resto.",
       "dejar a cada comunidad autónoma la decisión completa sobre el currículo escolar",
       "mantener unas enseñanzas mínimas comunes fijadas por el Estado",
       "currículo"),
    # Medio ambiente y energía
    _S("nuclear-prorroga", "environment_energy", "A",
       "Las centrales nucleares deben seguir funcionando más allá de su calendario de cierre.",
       "El calendario de cierre nuclear fija las fechas en que cada central deja de producir "
       "electricidad; lo acuerdan el Gobierno y las empresas propietarias.",
       "prolongar el funcionamiento de las centrales nucleares más allá del calendario de "
       "cierre",
       "cerrar las centrales nucleares según el calendario de cierre acordado",
       "energía nuclear"),
    _S("autoconsumo-solar", "environment_energy", "B",
       "Debe subvencionarse la instalación de placas solares en las viviendas.",
       "El autoconsumo solar consiste en producir electricidad con placas fotovoltaicas "
       "instaladas en el propio edificio para consumirla allí mismo.",
       "subvencionar la mitad del coste de las placas solares de autoconsumo en viviendas",
       "retirar las ayudas públicas al autoconsumo solar",
       "autoconsumo"),
    _S("coches-combustion", "environment_energy", "B",
       "Debe prohibirse la venta de coches nuevos de gasolina y diésel a partir de 2035.",
       "Los coches de combustión usan motores de gasolina o diésel; la Unión Europea acordó "
       "dejar de matricular coches nuevos que emitan CO2 a partir de 2035.",
       "prohibir la venta de coches nuevos de gasolina y diésel desde 2035",
       "permitir la venta de coches nuevos de gasolina y diésel sin fecha límite",
       "coche eléctrico"),
    _S("eolica-marina", "environment_energy", "D",
       "Deben autorizarse parques eólicos marinos frente a la costa.",
       "Un parque eólico marino es un conjunto de aerogeneradores instalados en el mar, fijos "
       "al fondo o flotantes, que producen electricidad con el viento.",
       "autorizar parques eólicos marinos frente a la costa",
       "excluir los parques eólicos marinos de las zonas de pesca y de las rías",
       "eólica marina"),
    # Impuestos
    _S("impuesto-patrimonio", "taxation", "A",
       "Debe mantenerse un impuesto sobre los grandes patrimonios.",
       "El impuesto sobre el patrimonio grava cada año el valor neto de los bienes y derechos de "
       "una persona por encima de un mínimo exento.",
       "mantener un impuesto anual sobre los patrimonios netos de más de tres millones de euros",
       "suprimir el impuesto sobre el patrimonio en todo el país",
       "patrimonio"),
    _S("iva-alimentos", "taxation", "A",
       "Debe aplicarse un IVA del 0 % a los alimentos básicos.",
       "El IVA es el impuesto que se paga al comprar bienes y servicios; los alimentos básicos "
       "son productos como el pan, la leche, los huevos o la fruta.",
       "aplicar un tipo de IVA del cero por ciento al pan, la leche, los huevos, la fruta y la "
       "verdura",
       "mantener el tipo reducido de IVA de los alimentos básicos sin rebajarlo más",
       "IVA"),
    _S("aportacion-comun", "taxation", "C",
       "La aportación de cada comunidad autónoma a la caja común del Estado debe tener un "
       "límite.",
       "El saldo fiscal es la diferencia entre lo que una comunidad aporta en impuestos al "
       "Estado y lo que recibe en gasto e inversión públicos.",
       "limitar por ley la aportación de cada comunidad autónoma a la caja común del Estado",
       "mantener la solidaridad entre comunidades sin límite a la aportación de cada una",
       "financiación autonómica"),
    # Pensiones
    _S("pensiones-ipc", "pensions", "A",
       "Las pensiones deben subir cada año como mínimo lo mismo que el IPC.",
       "El IPC, o índice de precios de consumo, mide cuánto suben de media los precios de los "
       "productos que compran los hogares a lo largo de un año.",
       "revalorizar todas las pensiones cada año al menos con el IPC",
       "ligar la subida anual de las pensiones a los ingresos de la Seguridad Social en lugar "
       "del IPC",
       "revalorización"),
    _S("jubilacion-68", "pensions", "A",
       "La edad legal de jubilación debe subir a 68 años.",
       "La edad legal de jubilación es la edad a partir de la cual se puede cobrar la pensión "
       "completa de jubilación sin aplicar reducciones.",
       "elevar de forma gradual la edad legal de jubilación hasta los sesenta y ocho años",
       "fijar la edad legal de jubilación en sesenta y cinco años",
       "edad de jubilación"),
    _S("seguridad-social-autonomica", "pensions", "C",
       "Cada comunidad autónoma debe gestionar su propia Seguridad Social.",
       "La Seguridad Social es el sistema público que paga pensiones y prestaciones con las "
       "cotizaciones de trabajadores y empresas; hoy es una caja única estatal.",
       "traspasar a cada comunidad autónoma la gestión de su propia Seguridad Social",
       "mantener la caja única de la Seguridad Social para todo el país",
       "caja única"),
    # Infraestructuras y transporte
    _S("peajes-autovias", "infrastructure_transport", "A",
       "Las autovías deben tener un peaje por uso que paguen los conductores.",
       "Un peaje es el pago por circular por una autopista o autovía; puede cobrarse en cabinas "
       "o con sistemas electrónicos según los kilómetros recorridos.",
       "implantar un peaje por kilómetro en las autopistas y autovías de alta capacidad",
       "mantener gratuitas todas las autovías financiadas con presupuestos públicos",
       "peajes"),
    _S("cercanias-gestion", "infrastructure_transport", "A",
       "La gestión de los trenes de cercanías debe pasar a las comunidades autónomas.",
       "Los trenes de cercanías son los servicios ferroviarios que unen una ciudad con su área "
       "metropolitana; hoy los gestiona una empresa pública estatal en casi todo el país.",
       "transferir la gestión de los trenes de cercanías a las comunidades autónomas que lo "
       "pidan",
       "mantener la gestión estatal única de todos los trenes de cercanías",
       "cercanías"),
    _S("tren-regional", "infrastructure_transport", "B",
       "Deben reabrirse las líneas de tren regional cerradas en las últimas décadas.",
       "Las líneas de tren regional unen ciudades medianas y pueblos; varias se cerraron por "
       "baja demanda y algunas se sustituyeron por autobuses.",
       "reabrir las líneas de tren regional cerradas que unan comarcas sin otro transporte "
       "público",
       "sustituir las líneas de tren regional con poca demanda por autobuses",
       "tren regional"),
    _S("aeropuertos-autonomicos", "infrastructure_transport", "C",
       "Cada aeropuerto debe ser gestionado por su comunidad autónoma.",
       "Hoy una empresa pública estatal gestiona en red la mayoría de los aeropuertos de interés "
       "general del país.",
       "traspasar la gestión de cada aeropuerto a su comunidad autónoma",
       "mantener la gestión en red de los aeropuertos por una empresa estatal",
       "aeropuertos"),
    _S("alta-velocidad-capitales", "infrastructure_transport", "D",
       "El tren de alta velocidad debe llegar a todas las capitales de provincia.",
       "La alta velocidad ferroviaria usa vías especiales para trenes que superan los 250 "
       "kilómetros por hora entre grandes ciudades.",
       "llevar la alta velocidad ferroviaria a todas las capitales de provincia",
       "dar prioridad a mejorar las líneas de tren convencional antes que extender la alta "
       "velocidad",
       "alta velocidad"),
    # Ciencia y digitalización
    _S("redes-edad", "science_digital", "B",
       "Las redes sociales deben verificar la edad de todos sus usuarios.",
       "La verificación de edad comprueba que quien abre una cuenta en una plataforma digital "
       "tiene la edad mínima exigida, por ejemplo con un documento o una aplicación.",
       "obligar a las redes sociales a verificar la edad de todos sus usuarios",
       "dejar la protección de los menores en las redes sociales en manos de las familias, sin "
       "verificación obligatoria de edad",
       "redes sociales"),
    _S("decisiones-automaticas", "science_digital", "B",
       "La administración debe avisar cuando una decisión la toma un sistema automático.",
       "Un sistema de decisión automatizada usa programas informáticos, a veces de inteligencia "
       "artificial, para resolver trámites como ayudas o sanciones.",
       "obligar a la administración a avisar cuando una decisión la toma un sistema automático",
       "permitir decisiones administrativas automáticas sin aviso específico a la persona "
       "interesada",
       "inteligencia artificial"),
    _S("gasto-investigacion", "science_digital", "B",
       "El gasto público en investigación debe llegar al 2 % del PIB.",
       "El PIB, o producto interior bruto, es el valor de todos los bienes y servicios "
       "producidos en un país en un año; sirve de referencia para medir el gasto.",
       "elevar el gasto público en investigación hasta el dos por ciento del PIB",
       "mantener el gasto público en investigación y atraer inversión privada con incentivos "
       "fiscales",
       "investigación"),
    # Derechos sociales e igualdad
    _S("ingreso-minimo", "social_rights_equality", "B",
       "El ingreso mínimo vital debe llegar a todos los hogares sin ingresos.",
       "El ingreso mínimo vital es una prestación mensual de la Seguridad Social para hogares "
       "con ingresos muy bajos, creada en 2020.",
       "ampliar el ingreso mínimo vital a todos los hogares sin ingresos",
       "sustituir el ingreso mínimo vital por ayudas ligadas a la búsqueda activa de empleo",
       "ingreso mínimo"),
    _S("dependencia-plazo", "social_rights_equality", "B",
       "Las ayudas a la dependencia deben resolverse en un plazo máximo de tres meses.",
       "La ley de dependencia reconoce ayudas y servicios a personas que necesitan el apoyo de "
       "otras para las actividades básicas de la vida diaria.",
       "resolver las ayudas a la dependencia en un plazo máximo de tres meses",
       "dejar los plazos de las ayudas a la dependencia a cada comunidad autónoma",
       "dependencia"),
    _S("permiso-nacimiento", "social_rights_equality", "B",
       "El permiso por nacimiento debe ampliarse a 24 semanas para cada progenitor.",
       "El permiso por nacimiento es el tiempo de descanso retribuido por la Seguridad Social "
       "tras el nacimiento o la adopción de un hijo.",
       "ampliar a veinticuatro semanas el permiso por nacimiento de cada progenitor",
       "mantener la duración del permiso por nacimiento y dar más flexibilidad para repartirlo",
       "permisos"),
    # Democracia e instituciones
    _S("voto-16", "democracy_institutions", "B",
       "La edad mínima para votar debe bajar a 16 años.",
       "Hoy pueden votar en las elecciones generales las personas con nacionalidad española "
       "mayores de dieciocho años inscritas en el censo electoral.",
       "rebajar a dieciséis años la edad mínima para votar",
       "mantener en dieciocho años la edad mínima para votar",
       "voto"),
    _S("listas-abiertas", "democracy_institutions", "B",
       "Los votantes deben poder elegir candidatos concretos dentro de cada lista electoral.",
       "En las elecciones al Congreso las listas son cerradas y bloqueadas: el votante elige una "
       "candidatura y no puede cambiar el orden de sus candidatos.",
       "implantar listas abiertas en las elecciones al Congreso",
       "mantener las listas cerradas y bloqueadas en las elecciones al Congreso",
       "sistema electoral"),
    _S("aforamiento", "democracy_institutions", "B",
       "Debe eliminarse el aforamiento de diputados y senadores.",
       "El aforamiento es la regla por la que ciertos cargos públicos solo pueden ser juzgados "
       "por un tribunal concreto, como el Tribunal Supremo.",
       "suprimir el aforamiento de diputados y senadores",
       "mantener el aforamiento de los cargos públicos previsto en la Constitución",
       "aforamiento"),
    # Justicia y seguridad
    _S("policia-autonomica", "justice_security", "C",
       "La policía autonómica debe asumir todas las funciones de seguridad en su territorio.",
       "Algunas comunidades autónomas tienen policía propia, que comparte funciones con la "
       "Policía Nacional y la Guardia Civil.",
       "transferir a la policía autonómica todas las funciones de seguridad ciudadana del "
       "territorio",
       "mantener a la Policía Nacional y la Guardia Civil en todas las comunidades autónomas",
       "policía"),
    # Modelo territorial
    _S("hacienda-propia", "territorial_model", "C",
       "Cada comunidad autónoma debe recaudar todos sus impuestos con una hacienda propia.",
       "Hoy la Agencia Tributaria estatal recauda la mayoría de los impuestos y el Estado "
       "reparte una parte a las comunidades con el sistema de financiación autonómica.",
       "crear una hacienda propia en cada comunidad autónoma que recaude todos sus impuestos",
       "mantener una agencia tributaria estatal única que recaude los grandes impuestos",
       "hacienda"),
    _S("consultas-autonomicas", "territorial_model", "C",
       "Las comunidades autónomas deben poder convocar consultas sobre su relación con el "
       "Estado.",
       "Una consulta es una votación en la que se pregunta a la ciudadanía sobre una cuestión "
       "política; hoy su convocatoria requiere la autorización del Estado.",
       "permitir a las comunidades autónomas convocar consultas sobre su relación con el Estado",
       "reservar al Estado la autorización de cualquier consulta sobre la organización "
       "territorial",
       "consultas"),
    # Agricultura y mundo rural
    _S("regadio", "agriculture_rural", "B",
       "Debe ampliarse la superficie de regadío con nuevas obras hidráulicas.",
       "El regadío es la superficie agrícola que recibe agua de forma artificial mediante "
       "canales, embalses o pozos, frente al cultivo de secano.",
       "ampliar la superficie de regadío con nuevos embalses y canales",
       "congelar la superficie de regadío y modernizar la existente para ahorrar agua",
       "regadío"),
    _S("ayudas-jovenes-agricultores", "agriculture_rural", "B",
       "Las ayudas agrarias deben dar prioridad a los agricultores jóvenes.",
       "La Política Agrícola Común es el sistema de ayudas de la Unión Europea a agricultores y "
       "ganaderos, que cada Estado reparte con sus propias reglas.",
       "reservar una parte mayor de las ayudas de la Política Agrícola Común a los agricultores "
       "menores de cuarenta años",
       "repartir las ayudas agrarias según la superficie cultivada, sin prioridad por edad",
       "relevo generacional"),
    _S("precio-coste", "agriculture_rural", "B",
       "Debe prohibirse comprar alimentos al agricultor por debajo de su coste de producción.",
       "La ley de la cadena alimentaria regula los contratos entre agricultores, industrias y "
       "supermercados para que el precio de compra cubra los costes.",
       "prohibir la compra de productos agrarios por debajo de su coste de producción",
       "dejar que los precios agrarios se fijen libremente entre productores y compradores",
       "cadena alimentaria"),
    _S("pesca-bajura", "agriculture_rural", "D",
       "Deben ampliarse las cuotas de pesca de la flota de bajura.",
       "La flota de bajura está formada por barcos pequeños que faenan cerca de la costa; sus "
       "capturas están limitadas por cuotas que se fijan en la Unión Europea.",
       "pedir más cuotas de pesca para la flota de bajura en el reparto europeo",
       "mantener las cuotas de pesca de bajura según los informes científicos de cada año",
       "pesca"),
    # Cultura y lenguas
    _S("lenguas-cooficiales", "culture_language", "C",
       "Las lenguas cooficiales deben poder usarse en todos los organismos del Estado.",
       "Las lenguas cooficiales son las que tienen carácter oficial junto al castellano en "
       "algunas comunidades autónomas, como el catalán, el gallego o el euskera.",
       "garantizar el uso de las lenguas cooficiales en todos los organismos del Estado",
       "usar el castellano como única lengua de trabajo en los organismos del Estado",
       "lenguas"),
    _S("selecciones-autonomicas", "culture_language", "C",
       "Las selecciones deportivas autonómicas deben poder competir en torneos internacionales "
       "oficiales.",
       "Las selecciones deportivas autonómicas representan a una comunidad autónoma; hoy solo "
       "las selecciones estatales disputan las competiciones oficiales internacionales.",
       "permitir que las selecciones deportivas autonómicas compitan en torneos "
       "internacionales oficiales",
       "mantener una única selección estatal en cada deporte para las competiciones oficiales",
       "deporte"),
)

STATEMENTS_BY_KEY: dict[str, DevStatement] = {s.key: s for s in STATEMENTS}

# --- Stances ------------------------------------------------------------------------

# Document key -> its stances: Statement key -> value (-2..2, never 0).
# ``cuarzo`` etc. are the national documents; ``turquesa`` and ``onixcat`` are the
# regional ones (``turquesa.md``, ``onix-cat.md``).
_TABLE = """
key                          cuarzo jade onix zafiro basalto turquesa onixcat
alquiler-limite              +2     +1   -2   -1     .       .        .
salario-minimo               +2     +1   -1   +1     .       .        .
jornada-35                   +2     .    -2   -1     .       .        .
impuesto-patrimonio          +1     +1   -2   -1     .       .        .
iva-alimentos                -1     .    +2   +1     .       .        .
copago-pensionistas          +2     +1   -1   .      .       .        .
gestion-sanitaria-publica    +1     +1   -2   -1     .       .        .
infantil-gratuita            +2     +2   -1   +1     .       .        .
conciertos-educativos        -2     .    +2   +1     .       .        .
nuclear-prorroga             -2     -1   +2   +1     .       .        .
pensiones-ipc                +2     +1   -1   +1     .       .        .
jubilacion-68                -2     .    +1   -1     .       .        .
peajes-autovias              -1     -1   +2   .      .       .        .
cercanias-gestion            +2     .    -2   +1     +2      .        +1
vivienda-publica             +2     +2   +1   -1     +1      .        .
aval-hipoteca                +1     -1   +2   +1     +1      .        .
pisos-turisticos             +1     +1   +1   -2     .       .        .
banca-publica                +1     +2   .    -1     .       .        .
cuota-autonomos              +1     -1   +2   +1     +1      .        .
despido-indemnizacion        +2     +1   +1   -1     .       .        .
teletrabajo                  +1     +2   .    -1     .       .        .
paro-formacion               +1     -2   +2   +1     .       .        .
plazo-operaciones            +2     +1   +2   -1     +1      .        .
psicologos-primaria          +2     +2   +1   -1     +1      .        .
dental-adultos               +2     -1   .    +1     +1      .        .
becas-renta                  +1     +1   +1   -2     .       .        .
fp-dual                      +1     -1   +2   +1     +1      .        .
ratio-aula                   +2     +1   +1   -1     .       .        .
autoconsumo-solar            +1     +2   +1   -1     +1      .        .
coches-combustion            +1     +2   +1   -2     .       .        .
regadio                      +1     -2   +2   +1     +1      .        .
ayudas-jovenes-agricultores  +1     +2   +1   -1     .       .        .
precio-coste                 +2     +1   +1   -1     .       .        .
redes-edad                   +1     -1   +2   +1     .       +1       .
decisiones-automaticas       +1     +2   .    -1     +1      .        .
gasto-investigacion          +2     +1   +1   -1     +1      .        .
ingreso-minimo               +2     +2   +1   -1     .       .        .
dependencia-plazo            +2     -1   +2   +1     .       .        .
permiso-nacimiento           +1     +2   .    -1     +1      .        .
voto-16                      +1     +1   +1   -2     .       .        .
listas-abiertas              +1     -1   +2   +1     .       .        .
aforamiento                  +2     +1   +2   -1     +1      .        .
tren-regional                +1     +2   +1   -1     .       .        .
hacienda-propia              -1     -1   -2   -1     +2      .        .
consultas-autonomicas        -2     -1   -2   -1     +2      .        .
lenguas-cooficiales          -1     .    -1   -1     +2      .        .
aeropuertos-autonomicos      -1     -1   -1   -2     +2      .        .
aportacion-comun             -2     -1   -1   -1     +2      .        .
policia-autonomica           -1     -1   -1   -1     +2      .        .
salario-minimo-autonomico    -1     -1   -1   -1     +2      .        .
curriculo-autonomico         -1     -1   -2   -1     +2      .        .
selecciones-autonomicas      -1     -1   -1   -1     +1      .        .
seguridad-social-autonomica  -2     -1   -1   -1     +2      .        .
pesca-bajura                 -1     .    -1   -1     .       +2       .
alta-velocidad-capitales     -1     .    -2   -1     .       +2       .
eolica-marina                +1     .    +1   +2     .       -2       .
"""


def _parse_table(table: str) -> tuple[tuple[str, ...], dict[str, dict[str, int]]]:
    lines = [line.split() for line in table.strip().splitlines()]
    columns = tuple(lines[0][1:])
    stances: dict[str, dict[str, int]] = {column: {} for column in columns}
    for row in lines[1:]:
        key, values = row[0], row[1:]
        if len(values) != len(columns):
            raise ValueError(f"stance row {key}: {len(values)} values for {len(columns)} columns")
        for column, raw in zip(columns, values, strict=True):
            if raw != ".":
                stances[column][key] = int(raw)
    return columns, stances


_COLUMNS, STANCES = _parse_table(_TABLE)

# Measures whose text is not the lead-in + action (document key, Statement key) -> text.
_OVERRIDES: dict[tuple[str, str], str] = {
    ("onixcat", "cercanias-gestion"): (
        "En Cataluña nos proponemos que la gestión completa de los trenes de cercanías pase a "
        "la comunidad autónoma."
    ),
    ("turquesa", "redes-edad"): (
        "Queremos que las redes sociales comprueben la edad de cada persona usuaria antes de "
        "abrirle una cuenta."
    ),
}

# Measures with no stance: (category, tag, action), assigned by document below.
_EXTRAS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "basalto": (
        ("infrastructure_transport", "puerto", "ampliar la conexión ferroviaria del puerto con el "
         "corredor de mercancías"),
        ("housing", "rehabilitación", "financiar la rehabilitación energética de los edificios "
         "de viviendas anteriores a 1980"),
        ("culture_language", "bibliotecas", "abrir las bibliotecas públicas también los domingos "
         "por la mañana"),
        ("health", "urgencias", "reforzar los servicios de urgencias de los hospitales comarcales "
         "en verano"),
        ("education", "comedores", "ampliar las becas de comedor escolar a todas las familias con "
         "ingresos bajos"),
        ("economy", "comercio", "apoyar al pequeño comercio con un plan de modernización de los "
         "mercados municipales"),
        ("science_digital", "conectividad", "llevar la fibra óptica a todos los núcleos de "
         "población de más de cien habitantes"),
        ("social_rights_equality", "mayores", "crear centros de día para personas mayores en "
         "todas las cabeceras de comarca"),
    ),
    "turquesa": (
        ("agriculture_rural", "despoblación", "crear una oficina de atención a nuevos pobladores "
         "en cada comarca rural"),
        ("culture_language", "patrimonio", "restaurar los hórreos y molinos catalogados como "
         "patrimonio etnográfico"),
        ("environment_energy", "incendios", "contratar todo el año a las brigadas de prevención "
         "de incendios forestales"),
    ),
    "onixcat": (
        ("infrastructure_transport", "carreteras", "renovar el firme de las carreteras comarcales "
         "con más de veinte años de uso"),
        ("environment_energy", "residuos", "instalar contenedores de residuos orgánicos en todos "
         "los municipios de más de mil habitantes"),
        ("employment", "empleo juvenil", "ofrecer un primer contrato en prácticas a los jóvenes "
         "que terminen la formación profesional"),
    ),
    "mica": (
        ("housing", "rehabilitación", "crear una ventanilla única para las ayudas a la "
         "rehabilitación de viviendas"),
        ("health", "urgencias", "abrir un nuevo centro de urgencias de atención primaria en cada "
         "distrito"),
        ("education", "comedores", "garantizar el comedor escolar gratuito en los colegios "
         "públicos"),
        ("infrastructure_transport", "carreteras", "soterrar las vías del tren a su paso por los "
         "barrios del sur"),
        ("environment_energy", "zonas verdes", "plantar un árbol por cada habitante en los "
         "próximos diez años"),
        ("culture_language", "bibliotecas", "ampliar el horario de las bibliotecas en época de "
         "exámenes"),
    ),
}

# Each document: file, front-matter Party, listed Parties, joint_for, lead-in, URL.
_LEAD_INS: dict[str, str] = {
    "cuarzo": "Proponemos",
    "jade": "Nos comprometemos a",
    "onix": "Vamos a",
    "zafiro": "Planteamos",
    "basalto": "Apostamos por",
    "turquesa": "Queremos",
    "onixcat": "En Cataluña nos proponemos",
    "mica": "Trabajaremos para",
}


@dataclass(frozen=True)
class _DocumentSpec:
    key: str
    file: str
    party: str
    parties: tuple[str, ...]
    joint_for: tuple[str, ...] = ()
    url: bool = True
    presentation: str = ""


_DOCUMENT_SPECS: tuple[_DocumentSpec, ...] = (
    _DocumentSpec("cuarzo", "cuarzo.md", "CUARZO", ("CUARZO",), presentation=(
        "Este programa recoge los compromisos de la candidatura para la próxima legislatura, "
        "ordenados por temas. Cada medida se presenta en una línea propia."
    )),
    _DocumentSpec("jade", "jade.md", "JADE", ("JADE", "TURQUESA"), presentation=(
        "Presentamos nuestras propuestas para toda la legislatura. Este texto también se aplica "
        "a la coalición con la que concurrimos en Galicia."
    )),
    _DocumentSpec("onix", "onix.md", "ONIX", ("ONIX", "ONIX-CAT"), presentation=(
        "Nuestro programa se organiza en bloques temáticos. Las medidas de cada bloque se "
        "aplicarán en los primeros cuatro años de gobierno."
    )),
    _DocumentSpec("onixcat", "onix-cat.md", "ONIX-CAT", ("ONIX-CAT",), presentation=(
        "Este documento completa el programa general de la candidatura con los compromisos "
        "propios de nuestras cuatro circunscripciones."
    )),
    _DocumentSpec("zafiro", "zafiro.md", "ZAFIRO", ("ZAFIRO",), url=False, presentation=(
        "La confederación presenta un programa común. Cada apartado reúne las medidas que "
        "defenderemos en el Congreso."
    )),
    _DocumentSpec("turquesa", "turquesa.md", "TURQUESA", ("TURQUESA",), joint_for=("TURQUESA",),
                  presentation=(
        "Programa conjunto de la coalición para sus cuatro circunscripciones. Prevalece sobre "
        "los programas de las fuerzas que la forman."
    )),
    _DocumentSpec("basalto", "basalto.md", "BASALTO", ("BASALTO",), presentation=(
        "El bloque concurre en una sola circunscripción. Sus propuestas se centran en el "
        "autogobierno y en los servicios públicos de proximidad."
    )),
    _DocumentSpec("mica", "mica.md", "MICA", ("MICA",), presentation=(
        "Un programa breve con nuestras prioridades municipales llevadas al Congreso."
    )),
)

PAGES_PER_DOCUMENT = 3


def disclaimer(name: str) -> str:
    """The first line of every manifesto (D8)."""
    return (
        f"Programa electoral ficticio de {name}, creado para el conjunto de datos de desarrollo "
        "de IdeologiApp. No corresponde a ningún partido real."
    )


_CATEGORY_NAMES = {entry.key: entry.name for entry in TOPIC_CATALOG}
_CATEGORY_ORDER = {entry.key: index for index, entry in enumerate(TOPIC_CATALOG)}
_PARTY_NAMES = {party.short_name: party.name for party in PARTIES}


def _measures_of(spec: _DocumentSpec) -> list[DevMeasure]:
    lead_in = _LEAD_INS[spec.key]
    measures: list[DevMeasure] = []
    for statement in STATEMENTS:
        value = STANCES.get(spec.key, {}).get(statement.key)
        if value is None:
            continue
        text = _OVERRIDES.get(
            (spec.key, statement.key),
            f"{lead_in} {statement.pro if value > 0 else statement.con}.",
        )
        measures.append(
            DevMeasure(text, statement.category, (statement.tag,), ((statement.key, value),))
        )
    for category, tag, action in _EXTRAS.get(spec.key, ()):
        measures.append(DevMeasure(f"{lead_in} {action}.", category, (tag,)))
    return measures


def _section(category: str, measures: Sequence[DevMeasure]) -> str:
    lines = [_CATEGORY_NAMES[category]]
    lines += [f"- {measure.text}" for measure in measures]
    return "\n".join(lines)


def _pages_of(spec: _DocumentSpec) -> tuple[DevPage, ...]:
    by_category: dict[str, list[DevMeasure]] = {}
    for measure in _measures_of(spec):
        by_category.setdefault(measure.category, []).append(measure)
    categories = sorted(by_category, key=lambda key: _CATEGORY_ORDER[key])
    count = min(PAGES_PER_DOCUMENT, len(categories))
    groups: list[list[str]] = [[] for _ in range(count)]
    for index, category in enumerate(categories):
        groups[index * count // len(categories)].append(category)
    pages: list[DevPage] = []
    for number, group in enumerate(groups, start=1):
        parts: list[str] = []
        if number == 1:
            parts += [disclaimer(_PARTY_NAMES[spec.party]), spec.presentation]
        parts += [_section(category, by_category[category]) for category in group]
        pages.append(
            DevPage(
                number,
                "\n\n".join(parts) + "\n",
                tuple(m for category in group for m in by_category[category]),
            )
        )
    return tuple(pages)


def _document(spec: _DocumentSpec) -> DevDocument:
    return DevDocument(
        file=spec.file,
        party=spec.party,
        parties=spec.parties,
        pages=_pages_of(spec),
        source_url=f"{URL_BASE}{spec.file.removesuffix('.md')}.pdf" if spec.url else None,
        joint_for=spec.joint_for,
    )


PIZARRA_DOCUMENT = DevDocument(
    file="pizarra.md",
    party="PIZARRA",
    parties=("PIZARRA",),
    pages=(
        DevPage(
            1,
            disclaimer("Candidatura Pizarra")
            + "\n\nÍndice\n\n1. Presentación de la candidatura\n2. Nuestro territorio\n"
            "3. Servicios públicos\n4. Economía local\n5. Compromisos con la ciudadanía\n",
        ),
    ),
    source_url=f"{URL_BASE}pizarra.pdf",
)

# Manifest ``[[documents]]`` order.
DOCUMENTS: tuple[DevDocument, ...] = (
    *(_document(spec) for spec in _DOCUMENT_SPECS),
    PIZARRA_DOCUMENT,
)
DOCUMENTS_BY_FILE: dict[str, DevDocument] = {d.file: d for d in DOCUMENTS}

# Every measure of every document, by text (texts are unique: ``check``).
MEASURES_BY_TEXT: dict[str, DevMeasure] = {
    measure.text: measure for document in DOCUMENTS for measure in document.measures
}


def measure_for(document_key: str, statement_key: str) -> DevMeasure:
    """The measure of ``document_key`` (``_DOCUMENT_SPECS`` key) with a stance on the Statement."""
    file = next(spec.file for spec in _DOCUMENT_SPECS if spec.key == document_key)
    for measure in DOCUMENTS_BY_FILE[file].measures:
        if any(key == statement_key for key, _ in measure.stances):
            return measure
    raise KeyError((document_key, statement_key))


# --- Conflicts, decision, rewording -----------------------------------------------------

CONFLICTS: tuple[DevConflict, ...] = (
    DevConflict(
        "TURQUESA",
        ("jade.md", "turquesa.md"),
        (measure_for("jade", "redes-edad").text, measure_for("turquesa", "redes-edad").text),
        "science_digital",
        "Una propuesta deja la protección de los menores en las redes sociales a las familias y "
        "la otra exige comprobar la edad de cada persona usuaria.",
    ),
    DevConflict(
        "ONIX-CAT",
        ("onix-cat.md", "onix.md"),
        (
            measure_for("onixcat", "cercanias-gestion").text,
            measure_for("onix", "cercanias-gestion").text,
        ),
        "infrastructure_transport",
        "Una propuesta mantiene la gestión estatal única de las cercanías y la otra la traspasa "
        "a la comunidad autónoma.",
    ),
)

DECISION = DevDecision(
    "ONIX-CAT",
    prevails="onix-cat.md",
    over="onix.md",
    reason="El programa propio de la candidatura concreta su posición sobre las cercanías en "
    "sus cuatro circunscripciones.",
)

REWORDING = DevRewording(
    statement="plazo-operaciones",
    text="La ley debe fijar cuántos días como máximo se puede esperar para una operación "
    "programada.",
    reason="La palabra «programadas» confunde: no queda claro que habla de operaciones no "
    "urgentes.",
    explanation="Misma medida y misma dirección; solo cambia el orden de la frase y usa "
    "palabras más sencillas.",
)

# --- Targets (realised numbers are pinned in the tests) ----------------------------------

MIN_POOL = 55
MIN_CATEGORIES = 10
MIN_PROPOSALS = 30

# --- Self-consistency (S7) ----------------------------------------------------------------


def _note_problems(statement: DevStatement) -> list[str]:
    problems: list[str] = []
    length = len(statement.note.strip())
    if not DEFAULT_CONTEXT_NOTE_MIN_CHARS <= length <= DEFAULT_CONTEXT_NOTE_MAX_CHARS:
        problems.append(f"statement {statement.key}: note has {length} characters")
    words = evaluative_matches(statement.note, DEFAULT_CONTEXT_NOTE_EVALUATIVE_WORDS)
    if words:
        problems.append(f"statement {statement.key}: note uses {', '.join(words)}")
    return problems


def _document_problems(document: DevDocument, seen: dict[str, str]) -> list[str]:
    problems: list[str] = []
    pages = document.page_texts()
    chunks = build_chunks(pages, PROPOSAL_CHUNK_MAX_CHARS)
    if len(chunks) != 1:
        problems.append(f"{document.file}: {len(chunks)} extraction chunks, expected 1")
    normalised = [normalize_for_match(text) for text in pages]
    for page in document.pages:
        for measure in page.measures:
            if measure.text in seen:
                problems.append(f"measure repeated in {seen[measure.text]} and {document.file}")
            seen[measure.text] = document.file
            if measure.text not in page.text:
                problems.append(f"{document.file}: measure not on page {page.number}")
            norm = normalize_for_match(measure.text)
            found = [n for n, text in enumerate(normalised, start=1) if norm in text]
            if found != [page.number]:
                problems.append(
                    f"{document.file}: measure found on pages {found}, expected {page.number}: "
                    f"{measure.text[:60]}"
                )
            for key, value in measure.stances:
                statement = STATEMENTS_BY_KEY.get(key)
                if statement is None:
                    problems.append(f"{document.file}: stance on unknown statement {key}")
                elif statement.category != measure.category:
                    problems.append(
                        f"{document.file}: stance on {key} ({statement.category}) from a "
                        f"{measure.category} measure"
                    )
                if value not in (-2, -1, 1, 2):
                    problems.append(f"{document.file}: stance {value} on {key}")
    return problems


def check() -> list[str]:
    """Content problems (S7); empty when the content is consistent. Pure."""
    problems: list[str] = []
    seen: dict[str, str] = {}
    for document in DOCUMENTS:
        problems += _document_problems(document, seen)
    texts: dict[str, str] = {}
    stanced = {key for d in DOCUMENTS for m in d.measures for key, _ in m.stances}
    for statement in STATEMENTS:
        norm = normalize_for_match(statement.text)
        if norm in texts:
            problems.append(f"statement {statement.key} repeats {texts[norm]}")
        texts[norm] = statement.key
        if statement.category not in _CATEGORY_NAMES:
            problems.append(f"statement {statement.key}: unknown category {statement.category}")
        if statement.key not in stanced:
            problems.append(f"statement {statement.key} has no stance")
        problems += _note_problems(statement)
    if normalize_for_match(REWORDING.text) in texts:
        problems.append("the rewording repeats a Statement")
    covered = {code for party in PARTIES for code in party.codes()}
    missing = [code for code in CODES if code not in covered]
    if missing:
        problems.append(f"Constituencies without candidature: {', '.join(missing)}")
    if len(STATEMENTS) < MIN_POOL:
        problems.append(f"pool of {len(STATEMENTS)} statements, expected at least {MIN_POOL}")
    if len({s.category for s in STATEMENTS}) < MIN_CATEGORIES:
        problems.append("too few categories")
    for conflict in CONFLICTS:
        for file, text in zip(conflict.files, conflict.texts, strict=True):
            if text not in {m.text for m in DOCUMENTS_BY_FILE[file].measures}:
                problems.append(f"conflict text not in {file}")
    return problems


def party_names() -> Mapping[str, str]:
    return dict(_PARTY_NAMES)


__all__ = [
    "CANDIDATURES_SOURCE",
    "CONFLICTS",
    "COUNTRY",
    "DECISION",
    "DOCUMENTS",
    "DOCUMENTS_BY_FILE",
    "ELECTION_DATE",
    "ELECTION_NAME",
    "ELECTION_TYPE",
    "EXTRACTOR",
    "GRAFITO_NOTE",
    "MEASURES_BY_TEXT",
    "PARTIES",
    "PIZARRA_NOTE",
    "REWORDING",
    "SLUG",
    "STANCES",
    "STATEMENTS",
    "STATEMENTS_BY_KEY",
    "DevConflict",
    "DevDecision",
    "DevDocument",
    "DevMeasure",
    "DevPage",
    "DevParty",
    "DevRewording",
    "DevStatement",
    "check",
    "disclaimer",
    "measure_for",
]
