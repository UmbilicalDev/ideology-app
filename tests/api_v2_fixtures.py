"""A hand-inserted published v2 Dataset Version for the public API tests (public-dataset-api-v2).

Direct inserts only (no provider, no pipeline), so every id and value is
known and the tests can compare whole bodies with hand-written JSON.

Election 1 (active), Dataset Version ``V2_VERSION`` (published, v2), made by run 1.

Parties (all of Election 1):

- 1 ``PA`` Partido Alfa (has a logo): runs in 01, 28, 31. Document 1 (URL,
  ``ALFA_URL``, hash ``a``) applies in 01, 28, 31.
- 2 ``BB`` Bloque Beta: runs in 01, 28, 31. Document 2 (upload, hash ``b``)
  applies only in 28 (partial scope); document 3 (upload, hash ``c``, a
  manifesto shared with Gamma) in 01, 28, 31.
- 3 ``CG`` Coalición Gamma: runs in 28, 31. Document 4 (URL, ``GAMMA_URL``,
  hash ``c``) in 28, 31.
- 4 ``XI`` Xarxa Independent: Excluded (``no_manifesto``), runs in 01 and 28.
- 5 ``UD`` Unión Delta: Excluded (``discarded_at_review``), runs in 31.

Proposals (id: hash, page, categories): 1 a p3 housing; 2 a p4 housing+economy;
3 a p5 economy; 6 a p6 housing (set aside in 01 and 28 by a conflict
decision: counts only in 31); 4 b p1 housing; 7 b p2 economy; 5 c p2
economy+housing (shared: Beta through document 3, Gamma through document 4).

Statements (id, position, topic): 104 p1 economy; 101 p2 housing (reworded:
``REWORDED_TEXT`` is the stored text, ``AI_TEXT`` the AI's); 102 p3 economy
(no note); 103 p4 housing.

Positions (Evidence: proposal(codes) in rank order):

- Alfa: 101 +2 [1(01,28,31), 6(31)]; 102 -1 [3]; 103 0 [2]; 104 +2 [3]
- Beta: 101 -2 [4(28)]; 102 +2 [5]; 103 +1 [5]; 104 -1 [7(28)]
- Gamma: 101 -1 [5]; 102 no stance (stored NULL); 103 -1 [5]; 104 no row

Constituencies: 28 available (ranks 101, 104, 102, 103; lengths [4]); 31
available (101, 102, 103; [3]); 01 unavailable ``too_few_statements`` (one
valid Statement, minimum 2); the other 49 ``fewer_than_two_parties``.
"""

import datetime as dt
import hashlib

from sqlalchemy import Engine

from ideology_app.config import GenerationMode
from ideology_app.constituencies import CONSTITUENCIES
from ideology_app.db import session_scope
from ideology_app.models import (
    ConstituencyStatement,
    DatasetVersion,
    DatasetVersionCandidature,
    DatasetVersionConstituency,
    DatasetVersionProposal,
    DatasetVersionStatus,
    Election,
    ElectionStatus,
    ElectionType,
    ModelGeneration,
    Party,
    PartyPosition,
    PartyPositionProposal,
    PipelineRun,
    PipelineRunStatus,
    Proposal,
    ProposalExtraction,
    ProposalExtractionStatus,
    SourceDocument,
    SourceDocumentOrigin,
    SourceDocumentStatus,
    Statement,
    StatementRewording,
)

V2_VERSION = 10
CREATED_AT = dt.datetime(2026, 11, 25, 10, 30, 0)
ALFA_URL = "https://alfa.example/programa.pdf"
GAMMA_URL = "https://gamma.example/programa.pdf"
LOGO = b"\x89PNG fixture bytes"
LOGO_SHA = hashlib.sha256(LOGO).hexdigest()

AI_TEXT = "TEXTO-DE-LA-IA sobre el alquiler."
REWORDED_TEXT = "Debe ponerse un tope al precio del alquiler."
REWORDING_REASON = "MOTIVO-DEL-OPERADOR"
REWORDING_EXPLANATION = "EXPLICACION-DEL-COMPROBADOR"

HASH = {"a": "a" * 64, "b": "b" * 64, "c": "c" * 64}
ALL3 = ["01", "28", "31"]

PARTIES = {
    1: ("Partido Alfa", "PA"),
    2: ("Bloque Beta", "BB"),
    3: ("Coalición Gamma", "CG"),
    4: ("Xarxa Independent", "XI"),
    5: ("Unión Delta", "UD"),
}
# party -> [(code, excluded reason)]
CANDIDATURES: dict[int, list[tuple[str, str | None]]] = {
    1: [("01", None), ("28", None), ("31", None)],
    2: [("01", None), ("28", None), ("31", None)],
    3: [("28", None), ("31", None)],
    4: [("01", "no_manifesto"), ("28", "no_manifesto")],
    5: [("31", "discarded_at_review")],
}
# id -> (party, origin url or None, hash, scope)
DOCUMENTS: dict[int, tuple[int, str | None, str, list[str]]] = {
    1: (1, ALFA_URL, "a", ALL3),
    2: (2, None, "b", ["28"]),
    3: (2, None, "c", ALL3),
    4: (3, GAMMA_URL, "c", ["28", "31"]),
}
# id -> (hash, ordinal, page, text, categories)
PROPOSALS: dict[int, tuple[str, int, int, str, list[str]]] = {
    1: ("a", 1, 3, "Bajar el precio del alquiler.", ["housing"]),
    2: ("a", 2, 4, "Ampliar la vivienda pública con fondos estatales.", ["housing", "economy"]),
    3: ("a", 3, 5, "Subir el salario mínimo cada año.", ["economy"]),
    6: ("a", 4, 6, "Congelar los alquileres en zonas tensionadas.", ["housing"]),
    4: ("b", 1, 1, "Liberalizar el suelo urbanizable.", ["housing"]),
    7: ("b", 2, 2, "Rebajar el impuesto de sociedades.", ["economy"]),
    5: ("c", 1, 2, "Bajar los impuestos a quien compra su primera vivienda.", ["economy", "housing"]),
}
# party -> counted Proposals in counted order: (proposal, document, codes)
FROZEN: dict[int, list[tuple[int, int, list[str]]]] = {
    1: [(1, 1, ALL3), (2, 1, ALL3), (3, 1, ALL3), (6, 1, ["31"])],
    2: [(4, 2, ["28"]), (7, 2, ["28"]), (5, 3, ALL3)],
    3: [(5, 4, ["28", "31"])],
}
# statement id -> (position, text, topic, note)
STATEMENTS: dict[int, tuple[int, str, str, str | None]] = {
    104: (1, "Debe subir el salario mínimo.", "economy", "Nota sobre el salario mínimo."),
    101: (2, REWORDED_TEXT, "housing", "Nota sobre el alquiler."),
    102: (3, "Deben bajarse los impuestos a las empresas.", "economy", None),
    103: (4, "Debe ampliarse la vivienda pública.", "housing", "Nota sobre vivienda pública."),
}
# (party, statement) -> (value, [proposal ids in rank order]); the codes come from FROZEN.
POSITIONS: dict[tuple[int, int], tuple[int | None, list[int]]] = {
    (1, 101): (2, [1, 6]),
    (1, 102): (-1, [3]),
    (1, 103): (0, [2]),
    (1, 104): (2, [3]),
    (2, 101): (-2, [4]),
    (2, 102): (2, [5]),
    (2, 103): (1, [5]),
    (2, 104): (-1, [7]),
    (3, 101): (-1, [5]),
    (3, 102): (None, []),
    (3, 103): (-1, [5]),
}
RANKS: dict[str, list[int]] = {"28": [101, 104, 102, 103], "31": [101, 102, 103]}
UNAVAILABLE_01 = ("too_few_statements", 1)


def _frozen_of(party_id: int, proposal_id: int) -> tuple[int, list[str]]:
    return next((doc, codes) for p, doc, codes in FROZEN[party_id] if p == proposal_id)


def seed_v2_version(engine: Engine) -> None:
    """Election 1 with the published v2 Dataset Version ``V2_VERSION`` described above."""
    with session_scope(engine) as session:
        session.add(
            Election(
                id=1, country="ES", type=ElectionType.GENERAL, date=dt.date(2026, 11, 29),
                name="Generales 2026", status=ElectionStatus.ACTIVE,
            )
        )
        session.flush()
        for party_id, (name, short) in PARTIES.items():
            party = Party(id=party_id, election_id=1, name=name, short_name=short)
            if party_id == 1:
                party.logo, party.logo_media_type, party.logo_sha256 = LOGO, "image/png", LOGO_SHA
            session.add(party)
        session.flush()
        for document_id, (party_id, url, key, _) in DOCUMENTS.items():
            session.add(
                SourceDocument(
                    id=document_id, party_id=party_id,
                    origin=SourceDocumentOrigin.URL if url else SourceDocumentOrigin.UPLOAD,
                    status=SourceDocumentStatus.PARSED, source_url=url,
                    content_hash=HASH[key], page_count=6, bundle_file=f"{key}.md",
                )
            )
        for extraction_id, key in enumerate(("a", "b", "c"), start=1):
            session.add(
                ProposalExtraction(
                    id=extraction_id, content_hash=HASH[key],
                    status=ProposalExtractionStatus.COMPLETE, llm_provider="fake",
                    llm_model="fake-model", prompt_version="v1", chunk_max_chars=12000,
                    chunk_count=1, check_version="v1", validated_count=1,
                )
            )
        session.flush()
        extraction = {"a": 1, "b": 2, "c": 3}
        for proposal_id, (key, ordinal, page, text, categories) in PROPOSALS.items():
            session.add(
                Proposal(
                    id=proposal_id, extraction_id=extraction[key], content_hash=HASH[key],
                    ordinal=ordinal, chunk_index=0, page=page, text=text,
                    categories=categories, tags=[],
                )
            )
        session.add(
            PipelineRun(
                id=1, election_id=1, status=PipelineRunStatus.PASSED, llm_provider="fake",
                llm_model="fake-model", generation_mode=GenerationMode.PRECOMPUTED,
                prompt_versions={}, llm_calls=0, input_tokens=0, output_tokens=0,
                model_generation=ModelGeneration.V2,
            )
        )
        session.flush()
        session.add(
            DatasetVersion(
                id=V2_VERSION, election_id=1, pipeline_run_id=1,
                status=DatasetVersionStatus.PUBLISHED, created_at=CREATED_AT,
                model_generation=ModelGeneration.V2,
            )
        )
        session.flush()
        for statement_id, (position, text, topic, note) in STATEMENTS.items():
            session.add(
                Statement(
                    id=statement_id, dataset_version_id=V2_VERSION, position=position,
                    text=text, topic=topic, context_note=note,
                )
            )
        session.flush()
        session.add(
            StatementRewording(
                statement_id=101, ai_text=AI_TEXT, reason=REWORDING_REASON,
                explanation=REWORDING_EXPLANATION,
            )
        )
        position_id = 0
        for (party_id, statement_id), (value, evidence) in POSITIONS.items():
            position_id += 1
            first = None
            if evidence:
                document_id, _ = _frozen_of(party_id, evidence[0])
                _, _, page, text, _ = PROPOSALS[evidence[0]]
                first = (document_id, text, page, DOCUMENTS[document_id][1])
            session.add(
                PartyPosition(
                    id=position_id, statement_id=statement_id, party_id=party_id, value=value,
                    evidence_source_document_id=None if first is None else first[0],
                    evidence_quote=None if first is None else first[1],
                    evidence_page=None if first is None else first[2],
                    evidence_url=None if first is None else first[3],
                )
            )
            session.flush()
            for rank, proposal_id in enumerate(evidence, start=1):
                document_id, codes = _frozen_of(party_id, proposal_id)
                session.add(
                    PartyPositionProposal(
                        party_position_id=position_id, rank=rank, proposal_id=proposal_id,
                        source_document_id=document_id, constituencies=codes,
                    )
                )
        for party_id, rows in FROZEN.items():
            for rank, (proposal_id, document_id, codes) in enumerate(rows, start=1):
                session.add(
                    DatasetVersionProposal(
                        dataset_version_id=V2_VERSION, party_id=party_id, rank=rank,
                        proposal_id=proposal_id, source_document_id=document_id,
                        constituencies=codes,
                    )
                )
        for code, _ in CONSTITUENCIES:
            if code in RANKS:
                n = len(RANKS[code])
                row = DatasetVersionConstituency(
                    available=True, unavailable_reason=None, valid_statement_count=n,
                    offered_lengths=[n], detail=None,
                )
            elif code == "01":
                row = DatasetVersionConstituency(
                    available=False, unavailable_reason=UNAVAILABLE_01[0],
                    valid_statement_count=UNAVAILABLE_01[1], offered_lengths=[],
                    detail={"statements": 1, "minimum": 2},
                )
            else:
                running = sum(
                    1 for rows in CANDIDATURES.values() for c, reason in rows
                    if c == code and reason is None
                )
                row = DatasetVersionConstituency(
                    available=False, unavailable_reason="fewer_than_two_parties",
                    valid_statement_count=0, offered_lengths=[], detail={"parties": running},
                )
            row.dataset_version_id, row.constituency_code = V2_VERSION, code
            session.add(row)
        for party_id, rows in CANDIDATURES.items():
            for code, reason in rows:
                session.add(
                    DatasetVersionCandidature(
                        dataset_version_id=V2_VERSION, party_id=party_id,
                        constituency_code=code, excluded_reason=reason,
                    )
                )
        for code, statement_ids in RANKS.items():
            for rank, statement_id in enumerate(statement_ids, start=1):
                session.add(
                    ConstituencyStatement(
                        dataset_version_id=V2_VERSION, constituency_code=code, rank=rank,
                        statement_id=statement_id,
                    )
                )


def add_version(
    engine: Engine,
    version_id: int,
    *,
    generation: ModelGeneration,
    status: DatasetVersionStatus,
) -> None:
    """An empty extra Dataset Version (its own run) of Election 1, for refusal tests."""
    with session_scope(engine) as session:
        session.add(
            PipelineRun(
                id=version_id, election_id=1, status=PipelineRunStatus.PASSED,
                llm_provider="fake", llm_model="fake-model",
                generation_mode=GenerationMode.PRECOMPUTED, prompt_versions={}, llm_calls=0,
                input_tokens=0, output_tokens=0, model_generation=generation,
            )
        )
        session.flush()
        session.add(
            DatasetVersion(
                id=version_id, election_id=1, pipeline_run_id=version_id, status=status,
                created_at=CREATED_AT, model_generation=generation,
            )
        )
