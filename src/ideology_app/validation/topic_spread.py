"""Check ``topic_spread`` (domain check 6): no topic dominates the Questionnaire.

The check runs on every questionnaire length the Dataset Version offers
(``base.offered_lengths``, ascending), each on its first L Statements in
position order. A topic fails a length when its share of those L Statements is
strictly above ``settings.max_topic_share_percent`` (integer arithmetic, no
floats). The reported percent is rounded up, so a failing topic always shows a
value above the maximum. A failing topic fails the whole run; no Statement is
dropped or moved and no length is dropped. With zero Statements the check
reports nothing (the Statement count is another check's job).
"""

from collections import Counter

from ideology_app.validation.base import (
    Check,
    ReportEntry,
    ValidationInput,
    length_prefix,
    offered_lengths,
)

NAME = "topic_spread"


def check_topic_spread(data: ValidationInput) -> list[ReportEntry]:
    """One run-level entry per length and topic above the share.

    Ordered by length, then by the topic's first appearance.
    """
    total_all = len(data.statements)
    percent = data.settings.max_topic_share_percent
    entries: list[ReportEntry] = []
    for length in offered_lengths(data):
        statements = data.statements[:length]
        total = len(statements)
        counts = Counter(s.topic for s in statements)
        prefix = length_prefix(length, total_all)
        for topic, count in counts.items():  # insertion order = first appearance
            if count * 100 > percent * total:
                share = -(-count * 100 // total)
                entries.append(
                    ReportEntry(
                        f"{prefix}topic {topic} has {count} of {total} statements "
                        f"({share}%); maximum is {percent}%"
                    )
                )
    return entries


TOPIC_SPREAD = Check(NAME, check_topic_spread)
