"""Token counting.

The memory counts tokens with the EmbeddingGemma 2 tokenizer when llama.cpp is
running (see ``runtime.LlamaServerTokenizer``). Without it, ``ApproxTokenizer``
gives a close estimate shaped like Gemma's SentencePiece tokenizer: common words
are one token, long words several, digits and CJK characters one each.

A tokenizer reports ``offsets(text)``: the end character of each token. That is
enough to count tokens over any span of the text and to cut a text to a budget.
"""

from __future__ import annotations

import bisect
import re
from typing import Protocol, Sequence

_APPROX = re.compile(
    r"(\s+)"
    r"|([\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff])"
    r"|(\d)"
    r"|([^\W\d_]+)"
    r"|(.)",
    re.S,
)

_WORD_CHUNK = 7


class Tokenizer(Protocol):
    name: str

    def offsets(self, text: str) -> list[int]:
        """End character offset of every token, in order."""
        ...


class ApproxTokenizer:
    name = "approx-v1"

    def offsets(self, text: str) -> list[int]:
        ends: list[int] = []
        for m in _APPROX.finditer(text):
            space, cjk, digit, word, other = m.groups()
            if space is not None:
                if "\n" in space or len(space) > 1:
                    ends.append(m.end())
            elif word is not None:
                start = m.start()
                n = len(word)
                for cut in range(_WORD_CHUNK, n, _WORD_CHUNK):
                    ends.append(start + cut)
                ends.append(m.end())
            else:
                ends.append(m.end())
        return ends


def count(tokenizer: Tokenizer, text: str) -> int:
    return len(tokenizer.offsets(text))


def tokens_in(ends: Sequence[int], start: int, end: int) -> int:
    """Number of tokens whose end falls in (start, end]."""
    return bisect.bisect_right(ends, end) - bisect.bisect_right(ends, start)


def cut(tokenizer: Tokenizer, text: str, max_tokens: int) -> tuple[str, int]:
    """Cut ``text`` to at most ``max_tokens`` tokens. Returns (prefix, tokens in it)."""
    ends = tokenizer.offsets(text)
    if len(ends) <= max_tokens:
        return text, len(ends)
    if max_tokens <= 0:
        return "", 0
    pos = ends[max_tokens - 1]
    return text[:pos], max_tokens
