"""Answer accuracy on LoCoMo with an LLM judge: the "J" score memory services publish.

    cogito-mem eval locomo-qa --data locomo10.json --context memory --budget 1000 --out results/qa-1000.json
    cogito-mem eval locomo-qa --data locomo10.json --context full --out results/qa-full.json
    cogito-mem eval locomo-qa compare results/qa-full.json results/qa-1000.json

``eval locomo`` measures retrieval with no model in the loop. Published memory systems (Mem0, Zep,
LangMem, MemOS, Memobase, Letta, ...) report something else: an answering model reads what the
memory returns, and a judging model marks the answer CORRECT or WRONG against LoCoMo's gold answer,
over the 1,540 questions of categories 1-4 (the adversarial category 5 is left out). This runs that
protocol, so the numbers can sit next to theirs.

Two protocols, with prompts taken word for word from Mem0's evaluation code (Apache-2.0):

- ``mem0-2025`` (default): the Mem0 paper's setup (arXiv 2504.19413), the one most published tables
  use. The answering model reads the memories through the prompt Mem0 used for Zep (temperature 0);
  the full-context baseline uses the paper's RAG prompt; the judge uses the paper's ACCURACY_PROMPT.
  Both models are gpt-4o-mini. Published: full context 72.90, Mem0 66.88, Zep 65.99, LangMem 58.10.
- ``mem0-2026``: mem0ai/memory-benchmarks on GitHub: a step-by-step answer prompt over up to 200
  memories in date order, and a lenient judge (one correct item of a list is enough; dates within
  14 days). Mem0 published 91.6-92.5 % with gpt-5 answering and judging.

Context arms:

- ``memory``: what cogito-mem returns for the question (``max_tokens`` = --budget, ``top_k`` =
  --top-k, ``as_of`` after the last session), each item as "<date>: <author>: <text>", in date order.
- ``full``: the whole conversation, every turn as "<session date> | <speaker>: <text>" (the paper's
  full-context baseline; it calibrates our judge against the published 72.90).

LLM calls go to any OpenAI-compatible endpoint: OpenRouter by default, keyed by OPENROUTER_API_KEY
or OPENROUTER_AUTH_TOKEN (``--env-file`` reads either from a file). Every call is cached by its exact
request in --llm-cache, so an interrupted run resumes and a rerun costs nothing.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as _dt
import hashlib
import http.client
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

from .. import timeutil
from ..memory import Config, Memory
from .common import record, sha256_file, utc_now
from .locomo import CATEGORIES, evidence_ids, load_conversation, sessions, turn_text
from .longmemeval import make_embedder, paired_bootstrap

# --------------------------------------------------------------------------- prompts: Mem0 paper (2025)

PAPER_ANSWER_PROMPT = """
    You are an intelligent memory assistant tasked with retrieving accurate information from conversation memories.

    # CONTEXT:
    You have access to memories from a conversation. These memories contain
    timestamped information that may be relevant to answering the question.

    # INSTRUCTIONS:
    1. Carefully analyze all provided memories
    2. Pay special attention to the timestamps to determine the answer
    3. If the question asks about a specific event or fact, look for direct evidence in the memories
    4. If the memories contain contradictory information, prioritize the most recent memory
    5. If there is a question about time references (like "last year", "two months ago", etc.),
       calculate the actual date based on the memory timestamp. For example, if a memory from
       4 May 2022 mentions "went to India last year," then the trip occurred in 2021.
    6. Always convert relative time references to specific dates, months, or years. For example,
       convert "last year" to "2022" or "two months ago" to "March 2023" based on the memory
       timestamp. Ignore the reference while answering the question.
    7. Focus only on the content of the memories. Do not confuse character
       names mentioned in memories with the actual users who created those memories.
    8. The answer should be less than 5-6 words.

    # APPROACH (Think step by step):
    1. First, examine all memories that contain information related to the question
    2. Examine the timestamps and content of these memories carefully
    3. Look for explicit mentions of dates, times, locations, or events that answer the question
    4. If the answer requires calculation (e.g., converting relative time references), show your work
    5. Formulate a precise, concise answer based solely on the evidence in the memories
    6. Double-check that your answer directly addresses the question asked
    7. Ensure your final answer is specific and avoids vague time references

    Memories:

    {memories}

    Question: {question}
    Answer:
    """

PAPER_FULL_SYSTEM = (
    "You are a helpful assistant that can answer "
    "questions based on the provided context."
    "If the question involves timing, use the conversation date for reference."
    "Provide the shortest possible answer."
    "Use words directly from the conversation when possible."
    "Avoid using subjects in your answer."
)

PAPER_FULL_PROMPT = """
# Question:
{question}

# Context:
{context}

# Short answer:
"""

PAPER_JUDGE_PROMPT = """
Your task is to label an answer to a question as ’CORRECT’ or ’WRONG’. You will be given the following data:
    (1) a question (posed by one user to another user),
    (2) a ’gold’ (ground truth) answer,
    (3) a generated answer
which you will score as CORRECT/WRONG.

The point of the question is to ask about something one user should know about the other user based on their prior conversations.
The gold answer will usually be a concise and short answer that includes the referenced topic, for example:
Question: Do you remember what I got the last time I went to Hawaii?
Gold answer: A shell necklace
The generated answer might be much longer, but you should be generous with your grading - as long as it touches on the same topic as the gold answer, it should be counted as CORRECT.

For time related questions, the gold answer will be a specific date, month, year, etc. The generated answer might be much longer or use relative time references (like "last Tuesday" or "next month"), but you should be generous with your grading - as long as it refers to the same date or time period as the gold answer, it should be counted as CORRECT. Even if the format differs (e.g., "May 7th" vs "7 May"), consider it CORRECT if it's the same date.

Now it's time for the real question:
Question: {question}
Gold answer: {gold_answer}
Generated answer: {generated_answer}

First, provide a short (one sentence) explanation of your reasoning, then finish with CORRECT or WRONG.
Do NOT include both CORRECT and WRONG in your response, or it will break the evaluation script.

Just return the label CORRECT or WRONG in a json format with the key as "label".
"""

# --------------------------------------------------------------------------- prompts: memory-benchmarks (2026)

BENCH_ANSWER_PROMPT = """You are answering a question using retrieved memories from past conversations. Follow these reasoning steps IN ORDER.

## Step 1: SCAN ALL MEMORIES
Read EVERY memory below from first to last. For each one that contains information relevant to the question, note it. Do NOT stop after finding the first relevant memory — important details are often scattered across many memories, including ones far down the list. Give equal weight to ALL memories regardless of position — a memory near the end is just as likely to contain the answer as one near the beginning. In these memories, "User" refers to the main person whose memories these are.

## Step 2: ENTITY VERIFICATION
Confirm each relevant memory is about the correct person/entity. If the question asks "What does Person A like?" and a memory says "Person B likes X", do NOT use that memory to answer about Person A. In two-person conversations, both speakers' actions are relevant — if the question asks about person A and a memory attributes an action to person B (the other speaker), that information is still valid evidence from their shared conversations, but always check the attribution is correct.

## Step 3: COMBINE AND CROSS-REFERENCE
- COMBINE facts from multiple memories about the same topic. If one memory says "won first place" and another says "performed a piece titled X," those describe the same event — connect them.
- For listing/counting questions, extract EVERY distinct item from ALL memories. A single memory may contain multiple items. Think about what CATEGORIES of answers the question could have, then re-scan specifically for each category.
- For counting questions ("how many times", "how many X"), enumerate each distinct instance explicitly with its date or context BEFORE giving a final count. Do not estimate — list them out, then count the list.
- DECOMPOSE complex sentences: "an immersive X with Y, enjoys Z" contains multiple distinct facts. Each could be the answer.
- Connect related facts across memories: if one says "nearby lake" and another says "Lake Tahoe is great for kayaking", the nearby lake IS Lake Tahoe. If one says "bought X in Paris", infer the country is France.

## Step 4: SELECT THE BEST ANSWER
- Do NOT assume the highest-ranked memory is correct. Multiple memories may describe different events for the same topic. Compare each candidate's relevance to the SPECIFIC question, not its retrieval score. A lower-ranked memory that directly answers the question beats a higher-ranked one that is only tangentially related.
- ALWAYS choose the MOST SPECIFIC detail available. A proper name, title, or number beats a generic description. Rate each candidate as HIGH specificity (name, title, number, specific activity) or LOW (generic description), and prefer HIGH.
- Report what someone actually DID, not what was offered or available to them. "Has not tried X yet" means X was NOT done — disqualify it. "Joined X" or "has done X" means it WAS done — prefer it.
- When multiple memories repeat the same generic fact, that repetition does NOT make it more correct than a single memory with a more specific answer.
- Photos depict what was IN the photo, not facts about someone's daily life. Prefer direct statements over photo descriptions for inferences.
- Re-read the question carefully before answering. If it asks "what aspect/type/kind", answer with the specific aspect. If it asks "what did they discover they both enjoy", answer with the specific thing, not the setting.

## Step 5: TEMPORAL GROUNDING
These conversations took place around {reference_date}. All events occurred in 2022-2024.
- Calculate time relative to this date, NOT today. Never output 2025 or 2026.
- Use dates explicitly stated in memory text. Do not invent or estimate dates.
- When a question asks what someone "shared" or "mentioned" on a date, that date is when they TALKED about it — look for events shortly BEFORE that date.
- For "how long" questions, find the start and end dates explicitly, then compute the duration. Do not guess.
- TEMPORAL DISAMBIGUATION: When you find MULTIPLE instances of similar events at different dates, enumerate them all with their dates before picking. If the question uses past tense + "the" → select the instance closest to (and before) the reference date. If future tense ("plans to", "going to") → select the earliest planned date. NEVER default to the first-mentioned or highest-scored instance — the DATE determines the answer.

## Step 6: INCLUSION CHECK (for lists and counts)
If you found items during reasoning that you're tempted to exclude from your answer — STOP. Include them unless you have STRONG evidence they are wrong. The most common mistake is finding relevant items but then dropping them due to overly strict filtering. More items is better than fewer when there is supporting evidence.
- For counting: after enumerating, re-verify each item. Check for duplicates (same event described differently) and ensure you haven't missed items from memories late in the list.
- The question assumes something happened. Find WHAT happened, don't say nothing happened.

## Step 7: COMMIT AND ANSWER
Give a direct, specific answer. NEVER say "not specified", "not mentioned", "no record", or "the memories don't say" — if ANY memory contains relevant information, give the best answer from available evidence. No hedging, no caveats. If the question asks for a list, include ALL items found. NEVER return an empty answer when relevant memories exist.
- NEVER generate specific names, titles, places, or dates that do not appear in any memory above. If no memory contains the specific detail the question asks for, answer with what the memories DO contain rather than guessing.
- For open-domain/opinion questions ("Would X do Y?", "Is X considered Z?"):
  * Follow the DIRECT causal reasoning in the memories. Do NOT construct elaborate counter-arguments.
  * "Would X still do Y without Z?" — If memories show X does Y BECAUSE of Z, then without Z, answer "likely no."
  * "Would X do Y again soon?" — If the most recent attempt involved a bad experience (accident, scare, trauma), answer "likely no." A recent negative experience outweighs historical positive patterns.
  * For trait questions ("Is X considered Z?"): weigh ALL evidence including symbolic/indirect references. If there is SOME but not strong evidence, answer with a qualified degree ("somewhat") rather than flat "no."

# Instructions

## Misc

1. Make reasonable deductions based on your memories. Memory shows store with a lot of working people -> store employs a lot of people
2. If a memory describes something recognizable (e.g., "romantic drama about memory and relationships"), you may name it (e.g., "Eternal Sunshine of the Spotless Mind").
3. Use domain knowledge to connect facts: a game exclusive to one platform implies ownership of that platform. An unnamed company deal can be linked to a previously expressed brand preference.

{memories}

Question: {question}

Work through Steps 1-7, then give your final answer after "ANSWER:".
"""

BENCH_JUDGE_SYSTEM = "You are evaluating conversational AI memory recall. Return JSON only with the format requested."

BENCH_JUDGE_PROMPT = """Label the generated answer as CORRECT or WRONG.

## Rules

1. **PARTIAL CREDIT**: If the generated answer includes AT LEAST ONE correct item from the gold answer's list, mark CORRECT. Getting 1 out of 2, 2 out of 4, etc. is always acceptable. Only mark WRONG if NONE of the gold answer items appear.

2. **PARAPHRASES COUNT**: Same concept in different words is CORRECT. "Chocolate raspberry tart" = "chocolate cake with raspberries". "Shelter meal service" = "volunteering at a homeless shelter". Emotions and sentiments in the same positive/negative family count as paraphrases: "proud" = "fulfilled" = "accomplished"; "huge success" = "relieved" = "thrilled" (all express positive achievement). Judge semantic meaning, not exact wording.

3. **EXTRA DETAIL IS FINE**: A longer answer that includes the gold answer's key facts plus additional information is CORRECT. Never penalize for being more detailed or specific. If the generated answer adds extra descriptive details beyond the gold answer while still referencing the same core entity or concept, mark CORRECT.

4. **DATE TOLERANCE**: Dates within 14 days of each other are CORRECT. Durations within 50% are CORRECT (e.g., "5 months" matches "six months"; "19 days" matches "two weeks"). Relative dates ("few days before November") match specific dates in the same window. A specific date (e.g., "February 2020") that is consistent with a vague reference (e.g., "a few years ago" relative to 2023) is CORRECT. Converting "last year" to the actual year (e.g., "2022" when conversations are in 2023) is CORRECT.

5. **SEMANTIC OVERLAP**: Judge whether the generated answer addresses the same topic and captures the core idea of the gold answer. Different wording, phrasing, or level of detail should not result in WRONG if the underlying concept matches. For EMOTIONS and FEELINGS questions, answers expressing sentiments in the same valence (positive/negative) about the same event are CORRECT — do not require the exact same emotion word.

6. **SAME REFERENT**: If the generated answer mentions or references the same named entity, character, person, or concept as the gold answer, mark CORRECT — even if the generated answer provides a different physical description or includes additional details. The key question is: does the generated answer identify the same core entity? If yes, it is CORRECT.

7. **FOCUS ON KNOWLEDGE, NOT WORDING**: The goal is to assess whether the system recalled the right fact. Minor differences in specificity, phrasing, or scope should not result in WRONG. Only mark WRONG when the generated answer demonstrates a genuinely different or incorrect understanding.

## ONLY mark WRONG if:
- The generated answer contains ZERO correct items from the gold answer
- The answer addresses a completely different topic

## Question
Question: {question}
Gold answer: {answer}
Generated answer: {response}

Return JSON with "reasoning" (one sentence) and "label" (CORRECT or WRONG). Do NOT include both labels."""

BENCH_MEMORY_LIMIT = 200

PROTOCOLS = {
    "mem0-2025": {"answer_model": "openai/gpt-4o-mini", "judge_model": "openai/gpt-4o-mini", "top_k": 100},
    "mem0-2026": {"answer_model": "openai/gpt-5", "judge_model": "openai/gpt-5", "top_k": 100},  # Mem0 used 200; 100 is our max
}

# --------------------------------------------------------------------------- the LLM client


def read_env_file(path: Path) -> dict[str, str]:
    """``KEY=value`` or ``KEY: value`` lines (a Claude Code style .env uses the latter)."""
    out = {}
    for line in path.read_text().splitlines():
        m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*[:=]\s*(.*?)\s*$", line)
        if m and not line.lstrip().startswith("#"):
            out[m.group(1)] = m.group(2).strip("'\"")
    return out


class LLM:
    """OpenAI-compatible chat completions with a request-keyed JSONL cache and retries."""

    RETRY = (408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529)

    def __init__(self, base_url: str, api_key: str, cache_path: Path | None, timeout: float = 300.0, retry_delay: float = 2.0):
        self.url = base_url.rstrip("/") + "/v1/chat/completions"
        self.api_key = api_key
        self.timeout = timeout
        self.retry_delay = retry_delay
        self.cache_path = cache_path
        self._lock = threading.Lock()
        self._cache: dict[str, dict] = {}
        self.calls = self.hits = 0
        self.cost = 0.0
        self.providers: dict[str, int] = defaultdict(int)
        if cache_path and cache_path.exists():
            for line in cache_path.read_text().splitlines():
                try:
                    entry = json.loads(line)
                    self._cache[entry["key"]] = entry["response"]
                except (ValueError, KeyError):
                    continue

    def chat(self, model: str, messages: list[dict], temperature: float | None = 0.0, json_mode: bool = False,
             reasoning: str | None = None, max_tokens: int | None = None, providers: list[str] | None = None) -> dict:
        body: dict = {"model": model, "messages": messages}
        if temperature is not None:
            body["temperature"] = temperature
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if reasoning:
            body["reasoning"] = {"effort": reasoning}
        if max_tokens:
            body["max_tokens"] = max_tokens  # also bounds what OpenRouter reserves for a request in flight
        if providers:  # OpenRouter routing: open models are served at different precisions by different hosts
            body["provider"] = {"order": providers, "allow_fallbacks": False}
        key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        with self._lock:
            if key in self._cache:
                self.hits += 1
                hit = self._cache[key]
                self.providers[f"{hit.get('model')} via {hit.get('provider')}"] += 1
                return hit
        data = json.dumps({**body, "usage": {"include": True}}).encode()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}", "X-Title": "cogito-mem eval"}
        delay = self.retry_delay
        for attempt in range(8):
            try:
                req = urllib.request.Request(self.url, data=data, headers=headers)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    res = json.loads(resp.read())
                if res.get("error"):
                    raise _Retry(str(res["error"])[:300])
                choice = res["choices"][0]
                out = {"content": choice["message"].get("content") or "", "finish_reason": choice.get("finish_reason"),
                       "usage": res.get("usage") or {}, "model": res.get("model"), "provider": res.get("provider")}  # fmt: skip
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300]
                if exc.code not in self.RETRY or attempt == 7:
                    raise RuntimeError(f"{model}: HTTP {exc.code}: {detail}") from None
            # a host can drop the connection mid-body (http.client.IncompleteRead) or reset it (OSError)
            except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError, KeyError, IndexError, _Retry) as exc:
                if attempt == 7:
                    raise RuntimeError(f"{model}: {exc}") from None
            time.sleep(delay)
            delay = min(delay * 2, 60.0)
        with self._lock:
            self.calls += 1
            self.cost += float(out["usage"].get("cost") or 0.0)
            self.providers[f"{out.get('model')} via {out.get('provider')}"] += 1
            self._cache[key] = out
            if self.cache_path:
                with open(self.cache_path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"key": key, "response": out}) + "\n")
        return out


class _Retry(Exception):
    pass


# --------------------------------------------------------------------------- formatting and scoring


def when_text(valid_at: str) -> str:
    """'2023-05-08T13:56:00.003Z' -> '1:56 pm on 8 May, 2023', the way LoCoMo writes session times."""
    dt = _dt.datetime.fromtimestamp(timeutil.parse(valid_at) / 1000, tz=_dt.timezone.utc)
    return f"{dt.hour % 12 or 12}:{dt.minute:02d} {'am' if dt.hour < 12 else 'pm'} on {dt.day} {dt:%B}, {dt.year}"


def day_text(valid_at: str) -> str:
    dt = _dt.datetime.fromtimestamp(timeutil.parse(valid_at) / 1000, tz=_dt.timezone.utc)
    return dt.strftime("%A, %B %d, %Y")


def simple_tokenize(text: str) -> list[str]:
    return text.lower().replace(".", " ").replace(",", " ").replace("!", " ").replace("?", " ").split()


def token_f1(prediction: str, reference: str) -> float:
    """Mem0's F1: over the sets of lower-cased words."""
    pred, ref = set(simple_tokenize(prediction)), set(simple_tokenize(reference))
    common = pred & ref
    if not pred or not ref or not common:
        return 0.0
    p, r = len(common) / len(pred), len(common) / len(ref)
    return 2 * p * r / (p + r)


def judge_label(content: str) -> tuple[bool, bool]:
    """(correct, parsed): the "label" of the judge's JSON, else the last CORRECT/WRONG in its text."""
    m = re.search(r"\{.*\}", content, re.S)
    if m:
        try:
            label = str(json.loads(m.group(0)).get("label", "")).strip().upper()
            if label in ("CORRECT", "WRONG"):
                return label == "CORRECT", True
        except ValueError:
            pass
    words = re.findall(r"\b(CORRECT|WRONG)\b", content.upper())
    return (bool(words) and words[-1] == "CORRECT"), False


def full_lines(sample: dict) -> list[tuple[str, str, str]]:
    """(session date, speaker, text) for every turn in date order."""
    conv = sample["conversation"]
    out = []
    for number, _when, turns in sessions(conv):
        date = " ".join(conv[f"session_{number}_date_time"].split())
        for turn in turns:
            text = turn_text(turn)
            if text:
                out.append((date, turn.get("speaker") or "unknown", text))
    return out


def without_captions(sample: dict) -> dict:
    """The sample with the photo captions removed: Mem0's harness gave every system the turn text only."""
    conv = {k: ([{f: v for f, v in t.items() if f != "blip_caption"} for t in turns] if isinstance(turns, list) else turns)
            for k, turns in sample["conversation"].items()}  # fmt: skip
    return {**sample, "conversation": conv}


def answer_messages(protocol: str, arm: str, question: str, sample: dict, items: list[dict], cache: bool = False) -> list[dict]:
    if protocol == "mem0-2025":
        if arm == "full":
            context = "".join(f"{d} | {s}: {t}\n" for d, s, t in full_lines(sample))
            return [{"role": "system", "content": PAPER_FULL_SYSTEM},
                    {"role": "user", "content": PAPER_FULL_PROMPT.format(question=question, context=context)}]  # fmt: skip
        memories = [f"{when_text(i['valid_at'])}: {i['author']}: {i['text']}" for i in items]
        prompt = PAPER_ANSWER_PROMPT.format(memories=json.dumps(memories, indent=4), question=question)
        return [{"role": "system", "content": prompt}]
    conv = sample["conversation"]
    last = sessions(conv)[-1][0]
    reference = " ".join(conv[f"session_{last}_date_time"].split())
    if arm == "full":
        lines = [f"({_dt.datetime.strptime(d, '%I:%M %p on %d %B, %Y'):%A, %B %d, %Y}) {s}: {t}"
                 for d, s, t in full_lines(sample)]  # fmt: skip
    else:
        lines = [f"({day_text(i['valid_at'])}) {i['author']}: {i['text']}" for i in items[:BENCH_MEMORY_LIMIT]]
    text = "\n".join(["The following memories are presented in chronological order (oldest to newest).", ""] + lines)
    prompt = BENCH_ANSWER_PROMPT.format(memories=text, question=question, reference_date=reference)
    if not cache:
        return [{"role": "user", "content": prompt}]
    # Instructions and memories come before the question, so they form a prefix the provider can cache:
    # with full context it is the same for every question of a conversation.
    cut = prompt.rindex("\n\nQuestion: ")
    return [{"role": "user", "content": [{"type": "text", "text": prompt[:cut], "cache_control": {"type": "ephemeral"}},
                                         {"type": "text", "text": prompt[cut:]}]}]  # fmt: skip


def judge_messages(protocol: str, question: str, gold: str, answer: str, category: int) -> list[dict]:
    if protocol == "mem0-2025":
        prompt = PAPER_JUDGE_PROMPT.format(question=question, gold_answer=gold, generated_answer=answer)
        return [{"role": "user", "content": prompt}]
    if category == 3 and ";" in gold:
        gold = gold.split(";")[0].strip()
    return [{"role": "system", "content": BENCH_JUDGE_SYSTEM},
            {"role": "user", "content": BENCH_JUDGE_PROMPT.format(question=question, answer=gold, response=answer)}]  # fmt: skip


def extract_answer(protocol: str, content: str) -> str:
    if protocol == "mem0-2026" and "ANSWER:" in content:
        return content.rsplit("ANSWER:", 1)[-1].strip()
    return content.strip()


# --------------------------------------------------------------------------- the run


def retrieve(mem: Memory, sample: dict, args: argparse.Namespace) -> tuple[dict, list[dict]]:
    """Load one conversation, then ask every question of categories 1-4. Returns (load info, rows)."""
    t0 = time.perf_counter()
    ids, tokens, _order, last = load_conversation(mem, sample)
    ns = mem.namespace("c")
    mem.embed_pending(ns, limit=10**9)
    mem.flush()
    load_s = time.perf_counter() - t0
    as_of = timeutil.format(last + 60_000)
    rows = []
    for qi, qa in enumerate(sample["qa"]):
        if qa.get("category") not in CATEGORIES or qa["category"] == 5 or "answer" not in qa:
            continue
        row = {"sample_id": sample.get("sample_id"), "q": qi, "category": CATEGORIES[qa["category"]],
               "category_id": qa["category"], "question": qa["question"], "gold": str(qa["answer"])}  # fmt: skip
        if args.context == "memory":
            t1 = time.perf_counter()
            resp = mem.handle({"op": "query", "namespace": "c", "text": qa["question"], "as_of": as_of,
                               "top_k": args.top_k, "max_tokens": args.budget})  # fmt: skip
            row["retrieve_ms"] = round((time.perf_counter() - t1) * 1000, 2)
            items = sorted(resp["items"], key=lambda i: i["valid_at"])
            row["items"] = [{"valid_at": i["valid_at"], "author": i["author"], "text": i["text"],
                             "message": i["source"]["id"]} for i in items]  # fmt: skip
            row["context_tokens"] = resp["tokens"]
            want = {ids[d] for d in evidence_ids(qa.get("evidence")) if d in ids}
            got = {i["source"]["id"] for i in resp["items"]}
            row["evidence_turns"] = len(want)
            row["evidence_covered"] = bool(want) and want <= got
        else:
            row["items"] = []
            row["context_tokens"] = sum(tokens.values())
        rows.append(row)
    return {"sample_id": sample.get("sample_id"), "turns": len(ids), "tokens": sum(tokens.values()),
            "load_and_embed_s": round(load_s, 2)}, rows  # fmt: skip


def answer_and_judge(llm: LLM, args: argparse.Namespace, sample: dict, row: dict) -> dict:
    # explicit cache marks for the providers that need them; OpenAI, DeepSeek and others cache prefixes on their own
    cache = args.prompt_cache and args.protocol == "mem0-2026" and args.answer_model.startswith(("anthropic/", "google/"))
    msgs = answer_messages(args.protocol, args.context, row["question"], sample, row["items"], cache=cache)
    # reasoning models take no temperature
    ans = llm.chat(args.answer_model, msgs, temperature=None if (args.no_temperature or args.answer_reasoning) else 0.0,
                   reasoning=args.answer_reasoning, max_tokens=args.answer_max_tokens,
                   providers=args.answer_provider.split(",") if args.answer_provider else None)  # fmt: skip
    answer = extract_answer(args.protocol, ans["content"])
    judgments, parsed = {}, True
    for judge in args.judges:
        jud = llm.chat(args.judge_model, judge_messages(judge, row["question"], row["gold"], answer, row["category_id"]),
                       temperature=None if (args.no_temperature or args.judge_reasoning) else 0.0, json_mode=True,
                       reasoning=args.judge_reasoning, max_tokens=args.judge_max_tokens)  # fmt: skip
        judgments[judge], ok = judge_label(jud["content"])
        parsed = parsed and ok
    usage = ans["usage"]
    out = {k: v for k, v in row.items() if k != "items"}
    out.update({"answer": answer, "correct": judgments[args.judges[0]], "judgments": judgments, "judge_parsed": parsed,
                "f1": round(token_f1(answer, row["gold"]), 4), "prompt_tokens": usage.get("prompt_tokens"),
                "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
                "completion_tokens": usage.get("completion_tokens"), "finish_reason": ans.get("finish_reason"),
                "items_returned": len(row["items"])})  # fmt: skip
    if args.keep_context:
        out["items"] = row["items"]
    return out


def _share(rows: list[dict], key: str) -> float:
    return round(100 * sum(bool(r[key]) for r in rows) / len(rows), 2) if rows else 0.0


def _mean(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def summarize(rows: list[dict]) -> dict:
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    summary = {
        "questions": len(rows),
        "J": _share(rows, "correct"),
        "F1": round(100 * sum(r["f1"] for r in rows) / len(rows), 2) if rows else 0.0,
        "by_category": {c: {"n": len(rs), "J": _share(rs, "correct"), "F1": round(100 * sum(r["f1"] for r in rs) / len(rs), 2)}
                        for c, rs in sorted(by_cat.items())},  # fmt: skip
        "mean_context_tokens": _mean([r.get("context_tokens") for r in rows]),
        "mean_prompt_tokens": _mean([r.get("prompt_tokens") for r in rows]),
        "mean_completion_tokens": _mean([r.get("completion_tokens") for r in rows]),
        "judge_unparsed": sum(not r["judge_parsed"] for r in rows),
        "empty_answers": sum(not r["answer"] for r in rows),
    }
    judges = list(rows[0].get("judgments") or {}) if rows else []
    if len(judges) > 1:
        summary["J_by_judge"] = {j: round(100 * sum(r["judgments"][j] for r in rows) / len(rows), 2) for j in judges}
    covered = [r for r in rows if r.get("evidence_turns")]
    if covered:
        hit = [r for r in covered if r["evidence_covered"]]
        miss = [r for r in covered if not r["evidence_covered"]]
        summary["evidence_covered"] = _share(covered, "evidence_covered")
        summary["J_when_evidence_covered"] = _share(hit, "correct")
        summary["J_when_evidence_missed"] = _share(miss, "correct")
    times = sorted(r["retrieve_ms"] for r in rows if "retrieve_ms" in r)
    if times:
        summary["retrieve_ms"] = {"median": times[len(times) // 2], "p95": times[int(0.95 * (len(times) - 1))]}
    return summary


def cmd_run(args: argparse.Namespace) -> int:
    defaults = PROTOCOLS[args.protocol]
    args.answer_model = args.answer_model or defaults["answer_model"]
    args.judge_model = args.judge_model or defaults["judge_model"]
    args.top_k = args.top_k or defaults["top_k"]
    args.judges = args.judges.split(",") if args.judges else [args.protocol]
    env = dict(os.environ)
    if args.env_file:
        env = {**read_env_file(Path(args.env_file)), **env}
    key = env.get(args.api_key_env) or env.get("OPENROUTER_API_KEY") or env.get("OPENROUTER_AUTH_TOKEN")
    if not key:
        print(f"no API key: set {args.api_key_env} or OPENROUTER_API_KEY, or pass --env-file", file=sys.stderr)
        return 2
    base = args.base_url or env.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api"
    llm = LLM(base, key, Path(args.llm_cache) if args.llm_cache else None)

    data_path = Path(args.data)
    samples = json.loads(data_path.read_text())
    if args.conversations:
        samples = [samples[int(i)] for i in args.conversations.split(",")]
    if args.no_captions:
        samples = [without_captions(s) for s in samples]
    embedder = rt = None
    if args.context == "memory" and args.search != "keyword":
        embedder, rt = make_embedder(args.embedder, Path(args.root).expanduser() if args.root else None)
    cfg = Config(search=args.search)
    meta = record(embedder.name if embedder is not None else None)
    meta.update({"dataset": str(data_path), "dataset_sha256": sha256_file(data_path), "protocol": args.protocol,
                 "context": args.context, "budget": args.budget if args.context == "memory" else None,
                 "top_k": args.top_k if args.context == "memory" else None, "search": cfg.search,
                 "captions": not args.no_captions,
                 "answer_model": args.answer_model, "judge_model": args.judge_model, "base_url": base, "judges": args.judges,
                 "answer_reasoning": args.answer_reasoning, "judge_reasoning": args.judge_reasoning,
                 "answer_max_tokens": args.answer_max_tokens, "judge_max_tokens": args.judge_max_tokens,
                 "prompt_cache": args.prompt_cache, "answer_provider": args.answer_provider})  # fmt: skip
    loads, rows = [], []
    t0 = time.perf_counter()
    try:
        for i, sample in enumerate(samples):
            with Memory(None, embedder=embedder, config=cfg, cache_path=args.cache) as mem:
                info, qrows = retrieve(mem, sample, args)
            if args.questions:
                qrows = qrows[: args.questions]
            loads.append(info)
            # the first question alone, so the rest can read the prompt prefix it leaves in the provider's cache
            done = [answer_and_judge(llm, args, sample, qrows[0])] if qrows else []
            with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
                done += list(pool.map(lambda r, s=sample: answer_and_judge(llm, args, s, r), qrows[1:]))
            rows.extend(done)
            s = summarize(rows)
            print(f"[{i + 1}/{len(samples)}] {info['sample_id']}: J {s['J']}  F1 {s['F1']}  ctx {s['mean_context_tokens']} tokens"
                  f"  ${llm.cost:.3f} ({llm.calls} calls, {llm.hits} cached, {time.perf_counter() - t0:.0f} s)",
                  file=sys.stderr)  # fmt: skip
    finally:
        if rt is not None:
            rt.stop()
    summary = summarize(rows)
    summary["llm_cost_usd"] = round(llm.cost, 4)
    meta["conversations"] = loads
    meta["served_by"] = dict(sorted(llm.providers.items(), key=lambda kv: -kv[1]))
    meta["finished_utc"] = utc_now()
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"meta": meta, "summary": summary, "per_question": rows}, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    a = json.loads(Path(args.a).read_text())
    b = json.loads(Path(args.b).read_text())

    def index(res):
        return {(r["sample_id"], r["q"]): r for r in res["per_question"]}

    ra, rb = index(a), index(b)
    common = sorted(set(ra) & set(rb))
    def ok(r):
        return r["judgments"][args.judge] if args.judge else r["correct"]

    xa = [float(ok(ra[q])) for q in common]
    xb = [float(ok(rb[q])) for q in common]
    mean, lo, hi = paired_bootstrap(xa, xb, args.bootstrap, args.seed)
    print(json.dumps({"questions": len(common), "a": round(100 * sum(xa) / len(xa), 2),
                      "b": round(100 * sum(xb) / len(xb), 2), "difference_points": round(100 * mean, 2),
                      "ci95_points": [round(100 * lo, 2), round(100 * hi, 2)]}, indent=2))  # fmt: skip
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cogito-mem eval locomo-qa", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    sub = p.add_subparsers(dest="cmd")
    c = sub.add_parser("compare", help="paired difference in J of two runs (b minus a)")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--judge", help="compare by this judge prompt's verdicts (default: each run's first)")
    c.add_argument("--bootstrap", type=int, default=10_000)
    c.add_argument("--seed", type=int, default=0)
    c.set_defaults(func=cmd_compare)
    p.add_argument("--data", help="locomo10.json")
    p.add_argument("--protocol", default="mem0-2025", choices=sorted(PROTOCOLS))
    p.add_argument("--context", default="memory", choices=["memory", "full"])
    p.add_argument("--budget", type=int, default=1000, help="max_tokens of the memory's answer (memory arm)")
    p.add_argument("--top-k", type=int, help="top_k of the query (default and maximum: 100)")
    p.add_argument("--search", default="hybrid", choices=["hybrid", "vector", "keyword"])
    p.add_argument("--embedder", default="auto", choices=["auto", "hash"])
    p.add_argument("--no-captions", action="store_true", help="drop the photo captions (as Mem0's 2025 harness did)")
    p.add_argument("--answer-model", help="default: the protocol's (openai/gpt-4o-mini or openai/gpt-5)")
    p.add_argument("--judge-model", help="default: the protocol's")
    p.add_argument("--no-temperature", action="store_true", help="send no temperature (for reasoning models)")
    p.add_argument("--answer-reasoning", help="reasoning effort for the answering model (e.g. minimal, low, medium)")
    p.add_argument("--judge-reasoning", help="reasoning effort for the judge")
    p.add_argument("--answer-max-tokens", type=int, help="output cap for an answer, reasoning included")
    p.add_argument("--judge-max-tokens", type=int, help="output cap for a judgment, reasoning included")
    p.add_argument("--answer-provider", help="OpenRouter providers for the answering model, in order, comma-separated; no others")
    p.add_argument("--judges", help="judge prompts to apply, comma-separated; the first gives J (default: the protocol's)")
    p.add_argument("--prompt-cache", action=argparse.BooleanOptionalAction, default=True,
                   help="mark the 2026 prompt's instructions and memories as a cacheable prefix (default: on)")
    p.add_argument("--base-url", help="OpenAI-compatible base URL (default $OPENROUTER_BASE_URL or OpenRouter)")
    p.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
    p.add_argument("--env-file", help="read API settings from this file (KEY=value or KEY: value)")
    p.add_argument("--llm-cache", default=str(Path.home() / ".cogito-mem" / "cache" / "locomo-qa-llm.jsonl"))
    p.add_argument("--cache", default=str(Path.home() / ".cogito-mem" / "cache" / "embeddings.sqlite3"))
    p.add_argument("--root", help="where llama.cpp and the model live (default ~/.cogito-mem)")
    p.add_argument("--conversations", help="comma-separated conversation indices (default: all 10)")
    p.add_argument("--questions", type=int, help="first N questions of each conversation (for a pilot)")
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--keep-context", action="store_true", help="store the returned items with each question")
    p.add_argument("--out")
    p.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.func is cmd_run and not args.data:
        build_parser().error("--data is required")
    return int(args.func(args) or 0)
