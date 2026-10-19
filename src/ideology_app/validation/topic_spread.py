"""Check ``topic_spread`` (domain check 6): no topic dominates the Questionnaire.

A topic fails when its share of the run's Statements is strictly above
``settings.max_topic_share_percent`` (integer arithmetic, no floats). The
reported percent is rounded up, so a failing topic always shows a value above
the maximum. A failing topic fails the whole run; no Statement is dropped or
moved. With zero Statements the check reports nothing (the Statement count is
another check's job).
"""

from collections import Counter

from ideology_app.validation.base import Check, ReportEntry, ValidationInput

NAME = "topic_spread"


def check_topic_spread(data: ValidationInput) -> list[ReportEntry]:
    """One run-level entry per topic above the share, in order of first appearance."""
    total = len(data.statements)
    if total == 0:
        return []
    percent = data.settings.max_topic_share_percent
    counts = Counter(s.topic for s in data.statements)
    entries: list[ReportEntry] = []
    for topic, count in counts.items():  # insertion order = first appearance
        if count * 100 > percent * total:
            share = -(-count * 100 // total)
            entries.append(
                ReportEntry(
                    f"topic {topic} has {count} of {total} statements ({share}%); "
                    f"maximum is {percent}%"
                )
            )
    return entries


TOPIC_SPREAD = Check(NAME, check_topic_spread)
