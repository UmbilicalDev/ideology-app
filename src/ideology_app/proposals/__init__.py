"""Phase 3 of guided ingestion: Proposals extracted from each kept manifesto.

- ``prompts``: the ``proposal_extraction`` prompt and its bounded output schema;
- ``extraction``: pure chunking and the verbatim/page check;
- ``store``: the database side (resume, finalize, reuse per content hash, the
  Ingestion Ledger handoff and the ledger count check).

See ``docs/specs/proposal-extraction.md``.
"""
