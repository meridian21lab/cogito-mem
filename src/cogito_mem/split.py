"""Split a long message into pieces (requirements §4).

A message of at most ``max_tokens`` tokens is stored whole. A longer one is split
at paragraph breaks; a paragraph that is still too long is split at sentence
breaks, and a sentence that is still too long at token boundaries. Neighbouring
parts are then packed greedily into pieces of at most ``max_tokens`` tokens, so a
piece never crosses the middle of a sentence unless the sentence alone is too long.

Every piece is a span ``[start, end)`` of the message in code points, with the
whitespace at its edges left out, so ``text[start:end]`` is the piece's text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .tokenizer import Tokenizer, tokens_in

PIECE_TOKENS = 256

_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n\s*")
_SENTENCE_END = re.compile(r"(?<=[.!?…;:])[\"')\]]*\s+|(?<=[。！？])|\n+")


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    tokens: int


def _strip(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _split_by(pattern: re.Pattern, text: str, start: int, end: int) -> list[tuple[int, int]]:
    parts = []
    pos = start
    for m in pattern.finditer(text, start, end):
        if m.end() == m.start() and m.start() in (start, end):
            continue
        a, b = _strip(text, pos, m.start())
        if b > a:
            parts.append((a, b))
        pos = m.end()
    a, b = _strip(text, pos, end)
    if b > a:
        parts.append((a, b))
    return parts


def _hard_split(ends: list[int], start: int, end: int, max_tokens: int) -> list[tuple[int, int]]:
    """Split [start, end) at token boundaries into runs of at most max_tokens tokens."""
    import bisect

    lo = bisect.bisect_right(ends, start)
    hi = bisect.bisect_right(ends, end)
    token_ends = ends[lo:hi]
    if not token_ends or token_ends[-1] != end:
        token_ends.append(end)
    parts = []
    pos = start
    for i in range(max_tokens - 1, len(token_ends), max_tokens):
        cut = token_ends[i]
        if cut <= pos:
            continue
        parts.append((pos, cut))
        pos = cut
    if pos < end:
        parts.append((pos, end))
    return parts


def split(text: str, tokenizer: Tokenizer, max_tokens: int = PIECE_TOKENS) -> list[Span]:
    ends = tokenizer.offsets(text)
    total = len(ends)
    if total <= max_tokens:
        return [Span(0, len(text), total)]

    def n(a: int, b: int) -> int:
        return tokens_in(ends, a, b)

    units: list[tuple[int, int]] = []
    for pa, pb in _split_by(_PARAGRAPH_BREAK, text, 0, len(text)):
        if n(pa, pb) <= max_tokens:
            units.append((pa, pb))
            continue
        for sa, sb in _split_by(_SENTENCE_END, text, pa, pb):
            if n(sa, sb) <= max_tokens:
                units.append((sa, sb))
            else:
                units.extend(_hard_split(ends, sa, sb, max_tokens))

    pieces: list[Span] = []
    cur_start, cur_end = units[0]
    for a, b in units[1:]:
        if n(cur_start, b) <= max_tokens:
            cur_end = b
        else:
            pieces.append(Span(cur_start, cur_end, n(cur_start, cur_end)))
            cur_start, cur_end = a, b
    pieces.append(Span(cur_start, cur_end, n(cur_start, cur_end)))
    return pieces
