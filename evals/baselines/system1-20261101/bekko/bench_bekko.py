"""Speed of BM25 + a tiny System-1 picker (bekko-system-one v0) on a LongMemEval_M history, CPU only.

    python bench_bekko.py MODEL_DIR DATA.json [N ...]
    BEKKO_DEVICE=mps python bench_bekko.py ...      # Apple GPU (Metal); cuda for NVIDIA; cpu by default
    BEKKO_THREADS=8 python bench_bekko.py ...       # CPU threads (default 4)
    BEKKO_COMPILE=1 python bench_bekko.py ...       # bekko's compile_inference() (torch.compile, Inductor)

Loads one M question into a keyword-only cogito-mem memory, takes the BM25 top N messages, and times
bekko's Choice over them (one decision, N options: a probability for every message). Also a toy check.
"""

import json
import statistics as st
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "src"))
model_dir, data_path = sys.argv[1], sys.argv[2]
sys.path.insert(0, model_dir)  # the audited inference_v0.py shipped with the weights

import torch  # noqa: E402

import os  # noqa: E402

DEVICE = os.environ.get("BEKKO_DEVICE", "cpu")
torch.set_num_threads(int(os.environ.get("BEKKO_THREADS", "4")))
from inference_v0 import BekkoSentenceTransformer  # noqa: E402

from cogito_mem.api import parse_query  # noqa: E402
from cogito_mem.evals.longmemeval import load_question  # noqa: E402
from cogito_mem.memory import Config, Memory  # noqa: E402

INSTRUCTION = "Which earlier message from the user's conversations with an AI assistant helps answer the question?"


def choice_request(question: str, texts: list[str]) -> dict:
    return {
        "state_json": json.dumps({"question": question}),
        "decisions": [{
            "id": "pick", "kind": "judgment", "type": "choice",
            "instructions_json": json.dumps(INSTRUCTION), "system_prompt": "",
            "criteria": [{"id": f"m{i}", "description_json": json.dumps(t), "value": None} for i, t in enumerate(texts)],
            "documents": [], "scoring": None,
        }],
    }


def pick(model, question, texts, **limits):
    out = model.predict(choice_request(question, texts), show_progress_bar=False, **limits)["pick"]
    return [out["probabilities"][f"m{i}"] for i in range(len(texts))]


t0 = time.perf_counter()
model = BekkoSentenceTransformer(model_dir, device=DEVICE, local_files_only=True, trust_remote_code=True)
if os.environ.get("BEKKO_COMPILE"):
    model.compile_inference()
print(f"loaded {model_dir.rsplit('/', 1)[-1]} on {DEVICE} in {time.perf_counter() - t0:.1f} s; torch threads {torch.get_num_threads()}")

toy = ["user: Let's call the staging server \"acorn\".", "assistant: Sure, I'll refer to the staging server as acorn.",
       "user: Can you give me a recipe for banana bread?", "assistant: The production database runs on Postgres 16.",
       "user: I deployed the new build to staging this morning."]
print("toy:", [round(p, 3) for p in pick(model, "What did we call the staging server?", toy)])

q = json.load(open(data_path))[0]
with Memory(None, embedder=None, config=Config(search="keyword")) as mem:
    load_question(mem, q)
    ns = mem.namespace("q")
    req = parse_query({"op": "query", "namespace": "q", "text": q["question"], "top_k": 300, "max_tokens": 100000})
    times = []
    for _ in range(20):
        t1 = time.perf_counter()
        cands = mem.candidates(ns, req, 2**62)
        times.append((time.perf_counter() - t1) * 1000)
    print(f"M history: {len(ns.messages)} messages; BM25 search median {st.median(times):.1f} ms")
    texts_all = ns.rank_texts([c.row for c in cands[:200]], "own")
for n in [int(x) for x in sys.argv[3:]] or [10, 30, 50, 100]:
    texts = texts_all[:n]
    for limit in (None, 128, 64):
        kw = {} if limit is None else {"document_length": limit}
        pick(model, q["question"], texts, **kw)  # warm-up
        ts = []
        for _ in range(5):
            t1 = time.perf_counter()
            pick(model, q["question"], texts, **kw)
            ts.append((time.perf_counter() - t1) * 1000)
        print(f"N={n:4d}  candidate tokens {'full' if limit is None else limit:>4}:  {st.median(ts):8.1f} ms median ({min(ts):.1f} min)")
