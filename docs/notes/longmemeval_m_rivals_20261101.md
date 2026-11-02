# Local memory projects on LongMemEval_M, session retrieval

Internal note. Stage 4 and half of claim B in `research_notes/long_history_eval_strategy_20261101.md`. Run 1-2 Nov 2026 on the author's Mac (M5 Max, 18 cores, 48 GB).
No rival had been measured at this size before.

## Result

**Cogi leads or matches every rival setting on the pass mark set before running.** All four projects ran on all 500 questions, in 12 settings, so the sample of 100 wasn't needed.

- **Nearest rivals at R@5, all 500:** hippo's benchmark script `turn_sym` is 3.2 points behind [+1.2, +5.4], hippo's `session_sym` 3.8 behind, and deja-vu 4.0 behind [+1.6, +6.4]. deja-vu is the nearest at its defaults.
- **No rival beats Cogi on R@5 or all@5 in any question type.** They tie at single-session-assistant (deja-vu, agentmemory, hippo's scripts) and on knowledge-update all@5 (hippo `session_sym`, 93.1).
- **Not a clear lead at R@10 against MemPalace `hybrid_v4`:** +2.0 [-0.2, +4.2]. It passes the mark (lower end above -5), but the interval reaches zero, so that pair is a match, not a win.

**Where rivals beat Cogi: speed and weight.**

- **Load time:** deja-vu loads a question's history in 1.6 s, agentmemory in 0.7 s and MemPalace in 3 s, all on CPU. Cogi embeds every turn on Metal: about 41 s per question while its cache was mostly cold (its log, questions 20 to 30). Its 4.6 s median in the result file relies on an embedding cache shared across questions, which a user with one history doesn't have.
- **Query time:** agentmemory's 5.8 ms median beats Cogi's 12.7 ms.
- **Footprint:** deja-vu peaks at 78 MB. Cogi's file doesn't record RAM or disk.

**What this doesn't show.** It covers session ranking only, with no token budget on Cogi's side, so it says nothing about answers or about what fits in a reply. See Limits. Claim B also names BEAM-1M and a matched budget, and neither has been run, so **claim B is half tested**.

## Scores

Every row below comes from `results/rivals-m/comparison.json`; `scripts/rivals_m/note_tables.py` prints these tables from it. Cogi is `results/long-history/m-recall-b904848.json`, commit `b904848`, hybrid search, no date cutoff. It was not rerun or changed for this.

**All 500**

| System | R@1 | R@3 | R@5 | R@10 | all@5 | all@10 | NDCG@10 | MRR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Cogi** | 74.4 | 89.0 | 93.0 | 96.0 | 76.0 | 85.0 | 0.818 | 0.825 |
| agentmemory, default (BM25) | 64.8 | 80.8 | 86.6 | 91.2 | 67.2 | 75.0 | 0.730 | 0.743 |
| agentmemory, older hybrid script | 62.4 | 78.6 | 85.4 | 91.2 | 61.0 | 74.8 | 0.709 | 0.724 |
| deja-vu, default | 71.0 | 83.2 | 89.0 | 92.2 | 69.8 | 76.4 | 0.761 | 0.786 |
| MemPalace, default (raw) | 55.4 | 74.6 | 81.4 | 87.4 | 56.8 | 70.6 | 0.662 | 0.672 |
| MemPalace, hybrid_v4 | 67.4 | 83.4 | 87.8 | 94.0 | 66.6 | 78.6 | 0.758 | 0.767 |
| hippo, default recall (4,000-token budget) | 67.0 | 68.2 | 68.2 | 68.2 | 22.4 | 22.4 | 0.486 | 0.676 |
| hippo, recall with budget lifted | 67.0 | 83.2 | 88.2 | 92.0 | 68.8 | 75.2 | 0.744 | 0.762 |
| hippo scripts, dense_only | 62.6 | 78.6 | 83.8 | 89.6 | 60.0 | 72.2 | 0.702 | 0.718 |
| hippo scripts, turn_sym | 69.8 | 86.8 | 89.8 | 93.8 | 69.4 | 79.4 | 0.774 | 0.790 |
| hippo scripts, turn_asym | 66.8 | 83.4 | 87.8 | 91.6 | 66.2 | 77.6 | 0.748 | 0.760 |
| hippo scripts, session_sym | 68.4 | 83.8 | 89.2 | 92.8 | 70.2 | 78.6 | 0.766 | 0.776 |
| hippo scripts, session_asym | 64.6 | 82.0 | 87.6 | 92.0 | 65.4 | 77.2 | 0.739 | 0.744 |

**The 470 answerable**

| System | R@1 | R@3 | R@5 | R@10 | all@5 | all@10 | NDCG@10 | MRR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Cogi** | 74.9 | 89.6 | 93.4 | 96.2 | 77.7 | 85.7 | 0.826 | 0.830 |
| agentmemory, default (BM25) | 65.7 | 81.7 | 87.2 | 91.5 | 68.5 | 76.0 | 0.740 | 0.750 |
| agentmemory, older hybrid script | 63.4 | 79.6 | 85.7 | 90.9 | 61.7 | 75.3 | 0.716 | 0.733 |
| deja-vu, default | 72.6 | 84.0 | 89.4 | 92.6 | 71.3 | 77.9 | 0.774 | 0.797 |
| MemPalace, default (raw) | 57.0 | 76.0 | 82.6 | 88.3 | 58.3 | 71.7 | 0.674 | 0.686 |
| MemPalace, hybrid_v4 | 68.7 | 84.5 | 88.7 | 94.7 | 68.3 | 80.0 | 0.770 | 0.779 |
| hippo, default recall (4,000-token budget) | 68.5 | 69.8 | 69.8 | 69.8 | 23.8 | 23.8 | 0.500 | 0.691 |
| hippo, recall with budget lifted | 68.5 | 84.3 | 88.9 | 92.8 | 70.2 | 76.6 | 0.757 | 0.774 |
| hippo scripts, dense_only | 64.0 | 80.0 | 85.3 | 91.1 | 61.3 | 73.6 | 0.716 | 0.732 |
| hippo scripts, turn_sym | 71.5 | 87.7 | 90.0 | 94.3 | 71.1 | 80.9 | 0.786 | 0.802 |
| hippo scripts, turn_asym | 68.5 | 84.5 | 89.1 | 92.3 | 67.9 | 79.1 | 0.762 | 0.774 |
| hippo scripts, session_sym | 69.8 | 85.3 | 90.0 | 93.4 | 71.5 | 80.2 | 0.779 | 0.789 |
| hippo scripts, session_asym | 66.4 | 83.6 | 88.9 | 92.8 | 67.0 | 78.9 | 0.754 | 0.759 |

**R@5 / all@5 by question type, answerable only**

| System | single-session-user (64) | single-session-assistant (56) | single-session-preference (30) | multi-session (121) | temporal-reasoning (127) | knowledge-update (72) |
|---|---:|---:|---:|---:|---:|---:|
| **Cogi** | 93.8 / 93.8 | 100.0 / 100.0 | 70.0 / 70.0 | 95.9 / 58.7 | 89.8 / 70.9 | 100.0 / 93.1 |
| agentmemory, default (BM25) | 87.5 / 87.5 | 100.0 / 100.0 | 50.0 / 50.0 | 90.9 / 48.8 | 81.9 / 59.1 | 95.8 / 84.7 |
| agentmemory, older hybrid script | 68.8 / 68.8 | 96.4 / 96.4 | 63.3 / 63.3 | 92.6 / 50.4 | 84.3 / 52.0 | 93.1 / 63.9 |
| deja-vu, default | 87.5 / 87.5 | 100.0 / 100.0 | 46.7 / 46.7 | 91.7 / 49.6 | 89.0 / 65.4 | 97.2 / 91.7 |
| MemPalace, default (raw) | 75.0 / 75.0 | 94.6 / 94.6 | 63.3 / 63.3 | 87.6 / 43.8 | 73.2 / 40.9 | 95.8 / 68.1 |
| MemPalace, hybrid_v4 | 87.5 / 87.5 | 96.4 / 96.4 | 53.3 / 53.3 | 90.9 / 48.8 | 86.6 / 55.1 | 98.6 / 91.7 |
| hippo, default recall (4,000-token budget) | 56.2 / 56.2 | 98.2 / 98.2 | 30.0 / 30.0 | 63.6 / 0.8 | 70.1 / 8.7 | 86.1 / 0.0 |
| hippo, recall with budget lifted | 90.6 / 90.6 | 98.2 / 98.2 | 56.7 / 56.7 | 89.3 / 48.8 | 86.6 / 61.4 | 97.2 / 87.5 |
| hippo scripts, dense_only | 82.8 / 82.8 | 100.0 / 100.0 | 60.0 / 60.0 | 84.3 / 42.1 | 81.1 / 43.3 | 95.8 / 76.4 |
| hippo scripts, turn_sym | 92.2 / 92.2 | 100.0 / 100.0 | 60.0 / 60.0 | 90.1 / 51.2 | 87.4 / 58.3 | 97.2 / 90.3 |
| hippo scripts, turn_asym | 87.5 / 87.5 | 100.0 / 100.0 | 63.3 / 63.3 | 89.3 / 48.8 | 86.6 / 52.8 | 97.2 / 86.1 |
| hippo scripts, session_sym | 89.1 / 89.1 | 100.0 / 100.0 | 60.0 / 60.0 | 91.7 / 51.2 | 87.4 / 59.8 | 97.2 / 93.1 |
| hippo scripts, session_asym | 85.9 / 85.9 | 100.0 / 100.0 | 60.0 / 60.0 | 90.1 / 47.9 | 86.6 / 52.8 | 97.2 / 84.7 |

Preference questions are hard for everyone, and multi-session all@5 stays low for everyone, Cogi included (58.7): one question needs every evidence session in five slots.

## Paired differences

Points, Cogi minus rival, paired by `question_id`, with a 95% interval from `paired_bootstrap` (10,000 resamples of questions, seed 0). **Pass mark, set before running:** the lower end is above -5.

**All 500**

| Rival setting | R@5 | R@10 | all@5 | Passes on all three |
|---|---|---|---|---|
| agentmemory, default (BM25) | +6.4 [+4.0, +9.0] | +4.8 [+2.6, +7.0] | +8.8 [+5.6, +12.0] | yes |
| agentmemory, older hybrid script | +7.6 [+4.6, +10.6] | +4.8 [+2.6, +7.2] | +15.0 [+11.2, +18.8] | yes |
| deja-vu, default | +4.0 [+1.6, +6.4] | +3.8 [+1.8, +5.8] | +6.2 [+3.4, +9.0] | yes |
| MemPalace, default (raw) | +11.6 [+8.4, +14.8] | +8.6 [+5.8, +11.4] | +19.2 [+15.2, +23.2] | yes |
| MemPalace, hybrid_v4 | +5.2 [+2.6, +7.8] | +2.0 [-0.2, +4.2] | +9.4 [+6.2, +12.8] | yes |
| hippo, default recall (4,000-token budget) | +24.8 [+21.0, +28.6] | +27.8 [+23.8, +31.8] | +53.6 [+49.2, +58.0] | yes |
| hippo, recall with budget lifted | +4.8 [+2.4, +7.2] | +4.0 [+2.2, +6.0] | +7.2 [+4.4, +10.2] | yes |
| hippo scripts, dense_only | +9.2 [+6.6, +12.0] | +6.4 [+4.0, +9.0] | +16.0 [+12.4, +19.8] | yes |
| hippo scripts, turn_sym | +3.2 [+1.2, +5.4] | +2.2 [+0.6, +4.0] | +6.6 [+3.8, +9.4] | yes |
| hippo scripts, turn_asym | +5.2 [+3.0, +7.4] | +4.4 [+2.4, +6.6] | +9.8 [+6.8, +12.8] | yes |
| hippo scripts, session_sym | +3.8 [+1.8, +6.0] | +3.2 [+1.4, +5.2] | +5.8 [+3.0, +8.6] | yes |
| hippo scripts, session_asym | +5.4 [+3.2, +7.8] | +4.0 [+2.0, +6.2] | +10.6 [+7.6, +13.8] | yes |

**The 470 answerable**

| Rival setting | R@5 | R@10 | all@5 | Passes on all three |
|---|---|---|---|---|
| agentmemory, default (BM25) | +6.2 [+3.6, +8.7] | +4.7 [+2.5, +7.0] | +9.2 [+6.0, +12.3] | yes |
| agentmemory, older hybrid script | +7.7 [+4.7, +10.6] | +5.3 [+3.0, +7.9] | +16.0 [+12.1, +19.8] | yes |
| deja-vu, default | +4.0 [+1.7, +6.6] | +3.6 [+1.5, +5.7] | +6.4 [+3.6, +9.2] | yes |
| MemPalace, default (raw) | +10.8 [+7.7, +14.0] | +7.9 [+5.1, +10.6] | +19.4 [+15.3, +23.6] | yes |
| MemPalace, hybrid_v4 | +4.7 [+2.1, +7.2] | +1.5 [-0.6, +3.6] | +9.4 [+6.2, +12.8] | yes |
| hippo, default recall (4,000-token budget) | +23.6 [+19.8, +27.4] | +26.4 [+22.3, +30.4] | +53.8 [+49.4, +58.3] | yes |
| hippo, recall with budget lifted | +4.5 [+2.1, +6.8] | +3.4 [+1.7, +5.3] | +7.5 [+4.7, +10.4] | yes |
| hippo scripts, dense_only | +8.1 [+5.5, +10.8] | +5.1 [+2.8, +7.7] | +16.4 [+12.6, +20.2] | yes |
| hippo scripts, turn_sym | +3.4 [+1.3, +5.5] | +1.9 [+0.2, +3.6] | +6.6 [+3.8, +9.6] | yes |
| hippo scripts, turn_asym | +4.3 [+2.1, +6.6] | +3.8 [+1.9, +6.0] | +9.8 [+6.8, +12.8] | yes |
| hippo scripts, session_sym | +3.4 [+1.5, +5.5] | +2.8 [+0.8, +4.7] | +6.2 [+3.4, +8.9] | yes |
| hippo scripts, session_asym | +4.5 [+2.3, +6.8] | +3.4 [+1.3, +5.5] | +10.6 [+7.5, +13.8] | yes |

Rivals do win individual questions: at R@5 the counts run from 1 to 11 questions that only the rival gets, against 22 to 125 that only Cogi gets (`comparison.json`, `cogi_only` / `rival_only`).

These 36 intervals per question set have no correction for multiple comparisons. All 12 settings were run once, with no tuning of any rival or of Cogi on these results.

## Speed and footprint

No other eval ran during any of these runs (checked every 5 minutes; details below). All ran under `nice -n 10`, in the sandbox.

| Setting | Load per question, median / p95 s | Query, median / p95 ms | Peak RSS MB | Disk per question MB | Wall s, all 500 |
|---|---:|---:|---:|---:|---:|
| **Cogi** (different day and conditions; see below) | 4.6 median; about 41 cold | 12.7 / 28.2 | not recorded | not recorded | 5,336 |
| agentmemory, default (BM25) | 0.68 / 0.72 | 5.8 / 7.5 | 605 | in memory; see below | 347 |
| agentmemory, older hybrid script | 2.98 / 3.05 | 9.1 / 11.8 | 779 | in memory | 1,495 |
| deja-vu, default | 1.64 / 2.62 | 27.7 / 70.2 | 78 | 4.7 | 919 |
| MemPalace, default (raw) | 2.95 / 3.03 | 71.8 / 74.4 | 4,046 | in memory; see below | 1,512 |
| MemPalace, hybrid_v4 | 4.17 / 4.35 | 143 / 307 | 4,755 | in memory | 2,167 |
| hippo, recall at default budget | 86.2 / 87.9 | 248 / 264 | 219 | 29.5 | 5,479, shared with the next row |
| hippo, recall with budget lifted | as above | 305 / 322 | 219 | 29.5 | shared with the row above |
| hippo scripts, all five | no store per question | 44.3 / 47.3 | 9,005 | 800 MB of vectors for the whole file | 3,697, of which 3,654 embedding on CPU |

Reading these:

- **Cogi isn't like for like.** Its result file predates this run, wasn't labelled for overlap, and its load figure benefits from an embedding cache shared across questions. The 41 s comes from `m-recall-b904848.log` (414 s for questions 20 to 30). That cache holds 537 MB for the 540,541 distinct turns.
- **hippo's load time is 476 Node processes,** one `hippo remember` per session, run 8 questions at a time. Its RSS is the largest single process. Recall time includes Node's start.
- **MemPalace's RSS grows during the run:** 1,006 MB after the first question, 4,046 MB by the end, in one process that deletes and recreates its collection per question. Cause not looked into. A single history needs about 1 GB.
- **Measured once, on the same median-size question:** MemPalace's documents in a persistent Chroma store take 7.0 MB (`disk-mempalace.json`). agentmemory's BM25 index serialises to 10.2 MB, plus 4.8 MB of session text (`disk-agentmemory.json`). Each stores the text differently from the others, so these aren't a ranking.
- **Cogi embeds every turn on the GPU,** which is why it's slower to load. The rivals' defaults use no vectors, or embed only a session's first tokens on CPU. That may explain part of Cogi's lead, but this run doesn't separate it: hippo's scripts also embed every turn and still rank below Cogi.

## From the short set to the long one

R@5 on all 500, S then M. S figures are from `results/rivals-m/repro-s/`, except as marked.

| System | S | M | Drop |
|---|---:|---:|---:|
| Cogi | 99.0 (strategy note, not rerun) | 93.0 | -6.0 |
| hippo scripts, turn_sym | 97.8 | 89.8 | -8.0 |
| deja-vu | 97.2 | 89.0 | -8.2 |
| hippo recall, budget lifted | 96.8 (published, 1.64.0) | 88.2 | -8.6 |
| hippo scripts, session_sym | 98.0 | 89.2 | -8.8 |
| agentmemory, BM25 | 96.4 | 86.6 | -9.8 |
| MemPalace, hybrid_v4 | 98.2 | 87.8 | -10.4 |
| agentmemory, older hybrid | 96.8 | 85.4 | -11.4 |
| MemPalace, raw | 96.6 | 81.4 | -15.2 |

On S these systems are within about 3 points of each other, and on M they spread over about 12. S scores don't predict the order on M: among rivals, MemPalace `hybrid_v4` has the best R@5 on S and on M falls behind hippo's `turn_sym` and `session_sym`, deja-vu and hippo's lifted recall. It does keep the rivals' best R@10 on M (94.0).

## Each project's setup

Versions are pinned by commit. Every setting scores whole sessions as ranked by the project; no project's code was changed except for adding the runner files named below.

| Project | Commit (version) | Setting | Indexes | Embedder | Path measured |
|---|---|---|---|---|---|
| deja-vu | `064f9ba` | Default | One transcript per session, both roles | None, lexical ladder | Production `index.Ensure` and search, as its `scripts/longmemeval` does |
| agentmemory | `c6c476d` (0.9.31) | Default | Whole sessions, both roles, role-flattened; repeated ids coalesced | None. BM25 unless a provider is set | Its eval's `bm25` adapter: production `SearchIndex`, no daemon or `iii` engine |
| agentmemory | same | Older hybrid | The same, with vectors from the first 512 characters | Local q8 MiniLM, weights 0.4 : 0.6 | `benchmark/longmemeval-bench.ts`, its 95.2 |
| MemPalace | `4f7745a` (3.12.0) | Default raw | Whole sessions, **user turns only**; the embedder reads the first 256 tokens | Chroma's default MiniLM ONNX | Its benchmark's `build_palace_and_retrieve`, in memory; not `mempalace mine` |
| MemPalace | same | hybrid_v4 | The same, plus keyword and date boosts and preference patterns | Same | The no-LLM setting behind its 98.4; some rules written from its S misses |
| hippo-memory | `cc59e7b` (3.1.0) | Default recall | Whole sessions, both roles, turn text joined | None. BM25, at most 200 candidates | `hippo remember` and `hippo recall` CLI, as its `recall_cli_haystack.py` |
| hippo-memory | same | Budget lifted | Same | Same | The same with `--budget 100000000`; returns a median of 580,312 tokens, so it measures ranking only |
| hippo-memory | same | Five scripts | Every distinct turn, both roles; BM25 statistics over the whole file | fp32 MiniLM, `@huggingface/transformers` 4.2.0 | Benchmark scripts behind its 98.0, **not** `hippo recall` |

**Settings tried:** deja-vu 1, agentmemory 2, MemPalace 2, hippo 7 (2 budgets of recall, 5 scripts). hippo's five are its own published set. On M, its best by R@5 is `turn_sym` and by all@5 `session_sym`, picked after the run, as its 98.0 was. Picking this way favours hippo, and it still doesn't reach Cogi.

**hippo's default is not comparable on budget.** At 4,000 tokens, whole sessions fill the budget in about two results (median 2 sessions, 3,774 tokens), so R@5 stays at R@1 plus a little. This is what a user gets from the CLI, but Cogi's row has no budget. Compare its ranking through the lifted row.

## Adapters, and whether they reproduce

Each adapter is a possible source of error, so each was run on LongMemEval-S and compared with what the project itself published (`results/rivals-m/repro-s/repro-comparison.json`).

| Setting | What the adapter changes | Check on S | Result |
|---|---|---|---|
| agentmemory BM25 | Reads a `[question]` file with its own loader; k 100 | Its receipts, strict recall per question | 470 of 470 agree; 84.7 both |
| deja-vu | Copy of its `runQuestion`; keeps the whole ranking | Its published totals (no per-question file) | R@1, R@5, R@10 and MRR all match: 88.2, 97.2, 98.6, 0.921 |
| MemPalace raw | Calls its function; keeps the first 100 and drops its unranked tail | Its results file | 500 of 500 with the same top 5 in the same order; 96.6 both |
| MemPalace hybrid_v4 | Same | Its 450 held-out questions | 450 of 450 agree; 98.4 both |
| hippo recall | Its steps from a per-question file; removes each store after use | Its raw file, on the sample of 100 | 100 of 100 outcomes agree at both budgets. That file is 1.52.5 and this is 3.1.0 |
| hippo scripts | Own driver using its `buildCorpus`, `tokenize`, `rrfFuse`; corpora in memory | Its published table | R@1, R@5, R@10 match in all five settings |
| agentmemory hybrid | Re-creates its script's loop | Its 2026 report | **Doesn't reproduce: higher.** Ours 96.8 / 98.8, published 95.2 / 98.6. Its report says that used an older pipeline. Being above it means the adapter doesn't under-serve the project |

## What failed or was left out

- **No project was ruled out.** Reading the install scripts and entry points turned up nothing that needed skipping. None of the installs needed its package scripts (`--ignore-scripts`).
- **Their own harnesses can't all read this file.** Node refuses a string over 512 MB (`ERR_STRING_TOO_LONG` on the 2.7 GB file), which stops agentmemory's loader and older script, and hippo's scripts on the data and again on their BM25 corpora. That's a limit of the harness and not the library. A per-question file gets past it for all of them.
- **Not run:** agentmemory's daemon path (needs its `iii` engine binary); `mempalace mine --mode convos`; hippo with MiniLM in `hippo recall`; optional embedders (deja-vu's endpoint, MemPalace's bge models); paid or LLM steps (voyage-3-large, MemPalace's LLM rerank), which no key was available for by design.

## Limits

- **Session rank only.** No answers were generated. This says nothing on whether a model answers correctly.
- **No token budget for Cogi.** It gets up to 300 items and no budget, with sessions ranked by first appearance. A session counted in its top 5 may not fit what the hook or a 1,000-token search returns, so this is not the delivered path. A matched-budget comparison is still to do.
- **Component paths.** Only deja-vu and hippo's recall go through what a user runs. agentmemory's and MemPalace's are the paths their published numbers use, not their daemon or `mine`, and hippo's scripts aren't a product feature at all.
- **Compressed time.** hippo filled each store in about a minute and a half, so its recency factor is almost flat. deja-vu's freshness uses real session dates, with the question date as "now".
- **hippo's scripts see the whole file.** BM25 statistics come from all 51,661 sessions in the dataset, more than any question's memory holds. A user couldn't have that, and it may help or hurt.
- **Not independent.** Run and written by Cogi's own side, with Cogi's scoring. The same question set has been open to everyone, so S-tuned rules, Cogi's included, carry over to M. No maintainer has reviewed their setup; the strategy note says to invite them before publishing.
- **Dataset.** LongMemEval_M is chat, not coding sessions. One hash: `9d79e552…`. MRR rests on rankings of different lengths (deja-vu about 50, most others 100), a small effect.

## Safety and process

- **Each rival ran with no network, no secrets and its own empty `HOME`.** `scripts/rivals_m/run_sandboxed.sh` uses `env -i` and macOS `sandbox-exec`. A probe in that sandbox was refused on `~/.claude`, `~/.cogito-mem`, the repo's `.env`, writing to the real home, and the network (`sandbox_probe.sh`). Rival homes hold only what was placed there: Chroma's model for MemPalace, and the probe's test file in deja-vu's.
- **Nothing touched** `~/.claude`, `~/.cogito-mem` or ports 7327, 7399, 7401. No `claude plugin install`, no `.env`, no keys. All Python ran from the project's own environment or `rivals-m/shared/env`, not the repo's `.venv`.
- **Network was used for installing only:** the four clones; npm and PyPI packages; the Go 1.27.3 toolchain (sha256 checked; deja-vu has no other dependencies); Chroma's MiniLM (sha256 checked); Xenova MiniLM q8 and fp32 at revision `751bff3`.
- **The agent harness refused `HOME=` written inline, and inline shell, in a command,** because it couldn't verify what git would do there. Installs went without it, using the tools' own cache settings. Rivals get `HOME` inside the wrapper script, as this run required. No script here runs git, and the sandbox denies writes outside `rivals-m`.
- **Waiting.** As the author asked, nothing was installed or run until other evals finished: 1 h 56 min, from 21:04 to 23:00 UTC on 1 Nov. Another 20 minutes came from my own test matching the check, which was no other job. Each job then checked every 5 minutes and none had to stop. **No run overlapped another eval.** `results/rivals-m/rows/*.wall.json`, `wait_checks.log`.

## Reproducing

The numbers are in `results/rivals-m/` (git-ignored): one result per setting, `comparison.json`, `tables.md`, `repro-s/`, `rows/` (raw rankings, logs, run times). Each result's `meta` holds commit, settings, machine and dataset hash. Scripts are in `scripts/rivals_m/`, with paths to this session's scratchpad written into them. In order: `prepare_data.py`, `sync.sh`, `jobs.sh <setting>:<data>:<sample>`, `final_all.sh`, `repro_compare.py`, `note_tables.py`. `.txt` files are copied into the clones, since they import project internals.

Fixed before any rival ran: `sample100` and `pilot20` (seed 7, stratified by type, in `manifest_m.json`). Only the pilot was used in the end, since the slowest full run took about 1.5 hours against the 12-hour limit.

# Matched token budgets

Added 2 Nov 2026. **Question:** of what each system returns within 1,000, 2,500 and 5,000 tokens, are all the messages holding the answer present?

## Rules, written before anything was scored

This section was committed before any coverage was computed for any system. Results follow below it.

**Evidence and denominator.** The `has_answer` turns of each question's answer sessions, skipping empty turns, as Cogi's loader does. Reported on all questions with such labels (479 on Cogi's turn table) and on the 470 answerable.

**Shared token counter.** The EmbeddingGemma 2 tokenizer through llama-server's `/tokenize`, the one Cogi's budgets already use. Every reply is measured with it and cut at the budget. Only message text counts: frames, headings, ids and dates are not counted for anyone, as Cogi's metadata isn't.

**Present.** A message is present if the reply shares at least 30 consecutive characters with it (lowercased, whitespace collapsed), or holds all of it if it is shorter. A question is covered when all its evidence messages are present. This is the text form of Cogi's rule, which counts a message if any piece of it is returned, even a piece without the answer. Cogi is scored both by message id, to reproduce its row, and by this rule; paired differences use this rule on both sides. **Sensitivity:** whole, meaning 95% of the message's 30-character windows are in the reply.

**Cogi.** Default settings, no reranker, frozen source `data/frozen/src-b904848`, no date cutoff, as in the row being reproduced. Rivals have no date cutoff either. If the row doesn't reproduce, this stops and is reported.

**Rule 1, as it ships.** Each project's real output, from reading its code:

| System | What it really returns | Budget option | How each budget is filled |
|---|---|---|---|
| Cogi | Pieces of messages, at most 256 tokens each | `max_tokens` | Its own |
| hippo recall | Whole sessions, as stored here | `recall --budget N`, counted as characters / 4; keeps the first result even when it's over | Real output at `--budget N`, cut at N by the shared counter |
| agentmemory | Whole sessions as stored here, the first clipped to fit; 20 results | `token_budget` on `mem::search`, counted as JSON length / 3 | `buildRecallResponse`, format `full`, called directly on its ranking; no daemon |
| deja-vu | `deja recall`: snippets from 5 sessions, 4 KB a page | None; `--offset` for later pages | Real CLI pages in order, walked by `--offset`, cut at N |
| MemPalace, product | `mine --mode convos` then search: drawers of up to 800 characters; 5 results by default | None; `--results` | 50 drawers asked for, in rank order, cut at N. Run on all 500 only if under the 12-hour limit, otherwise on `sample100`, stated plainly |
| MemPalace, benchmark `raw` and `hybrid_v4` | The session documents its published scores rank: user turns only | None | Whole documents in ranked order, the last cut at N, from the saved rankings |
| hippo scripts, 5 settings | Per session, its best dense turn (`content` in their rows) | None | Those turns in ranked order, the last cut at N |

**Rule 2, generous. Our construction, not a product feature.** From a rival's own ranked sessions, take every non-empty message of both roles in its **top 10** sessions, rank them by plain BM25 against the question (k1 1.2, b 0.75, lowercase alphanumeric words, no stemming, statistics over those messages only, zero scores dropped), and pack the budget exactly as Cogi packs: in order, the first cut if over, later ones skipped if they don't fit. It can't see labels and doesn't use Cogi's embeddings. Rankings are those saved from the last run; for hippo recall, the lifted ranking, since its default returns about two sessions. Top 5 and top 20 are reported as a sensitivity check, so 10 isn't a choice made afterwards.

**Generous, in pieces. Also our construction.** The same, but messages are first cut into consecutive 256-token pieces, Cogi's piece size, and BM25 ranks the pieces. This removes the size difference from the comparison.

**Control: Cogi's own session ranking through both generous rules.** Cogi's saved ranked sessions go through the same picker. With this:

- Rival generous-in-pieces minus rival as shipped: what smaller pieces alone give that rival.
- Cogi's ranking minus rival's ranking, through the same picker: what better session ranking gives.
- Cogi as shipped minus Cogi's ranking through the picker: what Cogi's own message-level search gives beyond that.

**Query time** is recorded at each budget as each system does it, and isn't comparable across process models: hippo and deja-vu start a process per call. Load time isn't a focus and isn't re-measured for this.

**Analysis.** Paired by `question_id`, Cogi minus rival, `paired_bootstrap` with 10,000 resamples of questions, seed 0.
