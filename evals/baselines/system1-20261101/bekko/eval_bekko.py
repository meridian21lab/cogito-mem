"""Recall of BM25 + a tiny System-1 picker (bekko-system-one v0) on LongMemEval_M, in the long-history row format.

    python eval_bekko.py MODEL_DIR DATA.json LIMIT OUT.json [choice|noul]

MODEL_DIR is a local copy of hotchpotch/bekko-system-one-v0-17m (or -68m); it runs that repository's own
inference_v0.py (trust_remote_code), with torch 2.10 CPU, transformers 5.17.0 and sentence-transformers 6.1.0.
DATA.json holds LongMemEval_M questions in the order of README.md (the 80-question test file).

Each question's history is loaded once into a keyword-only memory. `base` is keyword search alone; each other arm
takes the BM25 top N messages, cut to L tokens, and bekko's Choice puts a probability on every one; the reply lists
them by that probability (picking k messages = the first k). Rows are scored by the suite's own search_arm, so they
pair with evals/baselines/long-history-20261101/m-final.json by question_id. No date cutoff (LongMemEval's protocol).
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
model_dir, data_path, limit, out_path = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
sys.path.insert(0, model_dir)  # the audited inference_v0.py shipped with the weights

import torch  # noqa: E402

torch.set_num_threads(4)
from inference_v0 import BekkoSentenceTransformer  # noqa: E402

from cogito_mem.evals.long_history import NS, search_arm  # noqa: E402
from cogito_mem.evals.longmemeval import load, load_question  # noqa: E402
from cogito_mem.evals.system1 import CachedRanker, ScoreCache  # noqa: E402
from cogito_mem.memory import Config, Memory  # noqa: E402

INSTRUCTION = "Which earlier message from the user's conversations with an AI assistant helps answer the question?"
MODE = sys.argv[5] if len(sys.argv) > 5 else "choice"
ARMS = {  # name: (BM25 candidates N, tokens kept of each message, None = all)
    "pick10_128": (10, 128), "pick10_64": (10, 64), "pick30_64": (30, 64),
    "pick50_64": (50, 64), "pick100_64": (100, 64), "pick30_full": (30, None),
}


NOUL_INSTRUCTION = "Does this earlier message from the user's conversations with an AI assistant help answer the question, even partly?"
NOUL_ARMS = {"noul10_64": (10, 64), "noul30_64": (30, 64), "noul50_64": (50, 64)}


class BekkoNoul:
    """A yes/no decision per message (pointwise): several messages can be picked at once. One batched predict per list."""

    mode = "noul"

    def __init__(self, model, tokens, tag):
        self.model, self.tokens = model, tokens
        self.name = f"{tag}:noul:{tokens}"

    def score(self, query, texts):
        cut = [t[: 4 * self.tokens] for t in texts]  # about 4 characters a token; the message sits in the state
        requests = [{"state_json": json.dumps({"question": query, "message": t}), "decisions": [{
            "id": "helps", "kind": "judgment", "type": "noul", "instructions_json": json.dumps(NOUL_INSTRUCTION),
            "system_prompt": "", "documents": [], "scoring": None,
            "criteria": [{"id": "false", "description_json": json.dumps("The message does not help answer the question."), "value": None},
                         {"id": "true", "description_json": json.dumps("The message holds information that helps answer the question."), "value": None}]}]}
            for t in cut]
        out = self.model.predict(requests, show_progress_bar=False, batch_size=len(requests))
        return [o["helps"]["probability_yes"] for o in out]


class BekkoChoice:
    """One Choice over the candidates: a probability for every message (listwise, so cached per whole list)."""

    mode = "choice"

    def __init__(self, model, tokens, tag):
        self.model, self.tokens = model, tokens
        self.name = f"{tag}:choice:{tokens or 'all'}"

    def score(self, query, texts):
        request = {"state_json": json.dumps({"question": query}), "decisions": [{
            "id": "pick", "kind": "judgment", "type": "choice", "instructions_json": json.dumps(INSTRUCTION),
            "system_prompt": "", "documents": [], "scoring": None,
            "criteria": [{"id": f"m{i}", "description_json": json.dumps(t), "value": None} for i, t in enumerate(texts)]}]}
        kw = {} if self.tokens is None else {"document_length": self.tokens}
        out = self.model.predict(request, show_progress_bar=False, **kw)["pick"]
        return [out["probabilities"][f"m{i}"] for i in range(len(texts))]


model = BekkoSentenceTransformer(model_dir, device="cpu", local_files_only=True, trust_remote_code=True)
tag = Path(model_dir).name
cache = ScoreCache(None)  # in memory: each run scores afresh
if MODE == "noul":
    ARMS = NOUL_ARMS
    rankers = {t: CachedRanker(BekkoNoul(model, t, tag), cache) for t in {t for _, t in ARMS.values()}}
else:
    rankers = {t: CachedRanker(BekkoChoice(model, t, tag), cache) for t in {t for _, t in ARMS.values()}}
questions = load(Path(data_path))[:limit]
rows, t0 = [], time.perf_counter()
for i, q in enumerate(questions):
    with Memory(None, embedder=None, config=Config(search="keyword")) as mem:
        present = {str(s) for s in q["haystack_session_ids"]}
        want_sessions = {str(s) for s in q.get("answer_session_ids") or []} & present
        evidence, _ = load_question(mem, q, evidence_sessions=want_sessions)
        want_turns = set(evidence)
        row = {"question_id": q["question_id"], "question_type": q.get("question_type"), "abstention": "_abs" in str(q["question_id"]),
               "sessions": len(present), "messages": len(mem.namespace(NS).messages), "evidence_sessions": len(want_sessions),
               "evidence_turns": len(want_turns), "search": {}, "model_ms": {}}
        mem.reranker = None
        row["search"]["base"] = {"none": search_arm(mem, q, want_turns, want_sessions, None)}
        for name, (n, tokens) in ARMS.items():
            mem.config = Config(search="keyword", candidates=n, rerank_context="own", rerank_fusion="replace")
            mem.reranker = rankers[tokens]
            before = mem.reranker.stats["model_s"]
            row["search"][name] = {"none": search_arm(mem, q, want_turns, want_sessions, None)}
            row["model_ms"][name] = round(1000 * (mem.reranker.stats["model_s"] - before), 1)
        rows.append(row)
    if (i + 1) % 10 == 0 or i + 1 == len(questions):
        print(f"[{i + 1}/{len(questions)}] {time.perf_counter() - t0:.0f} s", file=sys.stderr, flush=True)
Path(out_path).write_text(json.dumps({"meta": {"model": tag, "mode": MODE, "arms": ARMS, "instruction": NOUL_INSTRUCTION if MODE == "noul" else INSTRUCTION, "data": data_path,
                                                "limit": limit, "torch_threads": 4}, "per_question": rows}))
print("wrote", out_path)
