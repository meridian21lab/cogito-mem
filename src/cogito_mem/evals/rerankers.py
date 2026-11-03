"""Cross-encoder rerankers for the evals (``--reranker``). Nothing outside the evals can start one.

Releases run plain hybrid search, so that installing stays simple. The results are in
``evals/baselines/long-history-20261101/README.md``.
"""

from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Sequence

import numpy as np

from ..runtime import PARALLEL, LlamaServer, RuntimeUnavailable, _post, find_llama_server


class LlamaServerReranker:
    """A cross-encoder reranker (stage-0 arm R) served by ``llama-server --reranking``."""

    def __init__(self, base: str, name: str):
        self.base = base
        self.name = name

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        if not texts:
            return []
        res = _post(self.base, "/v1/rerank", {"query": query, "documents": list(texts), "top_n": len(texts)})
        scores = [0.0] * len(texts)
        for r in res["results"]:  # type: ignore[index]
            s = float(r["relevance_score"])
            scores[r["index"]] = s if 0.0 <= s <= 1.0 else float(1.0 / (1.0 + np.exp(-s)))
        return scores


# Qwen3-Reranker is a model that answers "yes" or "no". GGUFs converted before llama.cpp PR #15824, most of those on Hugging
# Face, carry neither a rerank template nor a classifier, so ``--reranking`` returns noise (a clear match scored 9e-9). Prefer
# ggml-org's. For the others, the model's own prompt read as a probability does as well, about 20 ms each on Metal: on the 158
# tuning questions of LongMemEval_M, coverage at 1,000 tokens is 74.1 % this way and 74.7 % with ggml-org's.
_YES_NO_PROMPT = (
    '<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. '
    'Note that the answer can only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
    "<Instruct>: Given a query, retrieve passages that answer it\n\n<Query>: {query}\n\n<Document>: {document}"
    "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
)
_YES_NO_DOCUMENT_CHARS = 6000
_CONTROL_TOKEN = re.compile(r"<\|[^|<>\s]{1,40}\|>|</?think>|</?(?:Query|Document|Instruct)>", re.I)  # stored text may hold these
_YES_NO_FLOOR = 1e-6


class YesNoReranker:
    """A reranker that asks a model for "yes" or "no" about each text and scores by the probability of yes."""

    def __init__(self, base: str, name: str):
        self.base = base
        self.name = name

    def _one(self, query: str, text: str) -> float:
        prompt = _YES_NO_PROMPT.format(query=_CONTROL_TOKEN.sub(" ", query), document=_CONTROL_TOKEN.sub(" ", text[:_YES_NO_DOCUMENT_CHARS]))
        res = _post(self.base, "/completion", {"prompt": prompt, "n_predict": 1, "n_probs": 20, "temperature": 0, "cache_prompt": False})
        yes = no = _YES_NO_FLOOR
        for entry in res["completion_probabilities"][0]["top_logprobs"]:  # type: ignore[index]
            word = entry["token"].strip().lower()
            if word == "yes":
                yes += math.exp(entry["logprob"])
            elif word == "no":
                no += math.exp(entry["logprob"])
        return yes / (yes + no)

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        if not texts:
            return []
        with ThreadPoolExecutor(PARALLEL) as pool:
            return list(pool.map(lambda text: self._one(query, text), texts))


def _answers_yes_or_no(model: Path) -> bool:
    with open(model, "rb") as fh:
        head = fh.read(32 * 1024 * 1024)
    return b"qwen3" in head[:4096] and b"chat_template.rerank" not in head


def start_reranker(spec: str, root: Path | None) -> tuple[LlamaServerReranker | YesNoReranker, LlamaServer | None]:
    """``spec`` is a reranker GGUF path or the URL of a llama-server started with ``--reranking``."""
    if spec.startswith(("http://", "https://")):
        return LlamaServerReranker(spec.rstrip("/"), spec), None
    binary = find_llama_server(root)
    if binary is None:
        raise RuntimeUnavailable("llama-server was not found for the reranker")
    model = Path(spec).expanduser()
    if not model.exists():
        raise RuntimeUnavailable(f"reranker model {model} does not exist")
    log_path = root / "run" / "llama-reranker.log" if root is not None else None
    yes_no = _answers_yes_or_no(model)
    server = LlamaServer(binary, model, [] if yes_no else ["--reranking"], log_path)
    server.start()
    return (YesNoReranker if yes_no else LlamaServerReranker)(server.base, model.name), server
