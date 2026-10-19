"""Words for keyword search: lower-cased terms, and a query's terms without function words.

Kept apart from the BM25 index (which needs numpy) so the recall hook can use them and still start fast.
"""

from __future__ import annotations

import re

_TOKEN = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff]|[^\W_]+",
)


# Function words dropped from queries (not from the index): in a question like "do you
# remember what we said about X?" they would otherwise outweigh X in short messages.
STOPWORDS = frozenset(
    """
    a about above after again against all am an and any are as at be because been before being below
    between both but by can could did do does doing don down during each few for from further had has
    have having he her here hers herself him himself his how i if in into is it its itself just me
    more most my myself no nor not now of off on once only or other our ours ourselves out over own
    same she should so some such than that the their theirs them themselves then there these they this
    those through to too under until up very was we were what when where which while who whom why will
    with would you your yours yourself yourselves s t ll re ve d m
    """.split()
)


def query_terms(text: str) -> set[str]:
    """The query's terms without function words, unless nothing else is left."""
    all_terms = set(terms(text))
    content = all_terms - STOPWORDS
    return content or all_terms


def terms(text: str) -> list[str]:
    """Lower-cased word terms. CJK characters are one term each."""
    return _TOKEN.findall(text.lower())
