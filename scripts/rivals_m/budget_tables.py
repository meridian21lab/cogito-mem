#!/usr/bin/env python3
"""Prints the note's budget tables from results/rivals-m/budget/comparison.json.

    python budget_tables.py <comparison.json>
"""
from __future__ import annotations

import json
import sys

BUDGETS = ("1000", "2500", "5000")
SHIPPED = {
    "shipped_deja": "deja-vu, `recall` pages",
    "shipped_agentmemory-bm25": "agentmemory, recall response on BM25",
    "shipped_agentmemory-hybrid": "agentmemory, recall response on older hybrid",
    "shipped_mempalace-mine": "MemPalace, `mine` + search drawers",
    "shipped_mempalace-raw": "MemPalace, benchmark raw documents",
    "shipped_mempalace-hybrid_v4": "MemPalace, benchmark hybrid_v4 documents",
    "shipped_hippo": "hippo, `recall --budget`",
    "shipped_hippo-scripts_turn_sym": "hippo scripts, turn_sym best turns",
    "shipped_hippo-scripts_session_sym": "hippo scripts, session_sym best turns",
    "shipped_hippo-scripts_turn_asym": "hippo scripts, turn_asym best turns",
    "shipped_hippo-scripts_session_asym": "hippo scripts, session_asym best turns",
    "shipped_hippo-scripts_dense_only": "hippo scripts, dense_only best turns",
}
RANKS = {
    "cogi-ranking": "Cogi's session ranking (control)",
    "deja-default": "deja-vu",
    "agentmemory-bm25": "agentmemory BM25",
    "agentmemory-hybrid": "agentmemory older hybrid",
    "mempalace-raw": "MemPalace raw",
    "mempalace-hybrid_v4": "MemPalace hybrid_v4",
    "hippo-lifted": "hippo recall ranking",
    "hippo-best_turn_sym": "hippo scripts, turn_sym",
    "hippo-best_session_sym": "hippo scripts, session_sym",
}
PAIRS = {  # shipped row -> ranking row, for the decomposition
    "shipped_deja": "deja-default",
    "shipped_agentmemory-bm25": "agentmemory-bm25",
    "shipped_agentmemory-hybrid": "agentmemory-hybrid",
    "shipped_mempalace-raw": "mempalace-raw",
    "shipped_mempalace-hybrid_v4": "mempalace-hybrid_v4",
    "shipped_hippo": "hippo-lifted",
    "shipped_hippo-scripts_turn_sym": "hippo-best_turn_sym",
    "shipped_hippo-scripts_session_sym": "hippo-best_session_sym",
}


def main() -> int:
    c = json.load(open(sys.argv[1]))
    r = c["rivals"]
    cogi = c["cogi"]

    def cov(entry, b, key="coverage", s="labelled"):
        return 100 * entry["summary"][s][b][key]

    print(f"Cogi by message id, labelled {c['cogi']['labelled']['n']}:", c["cogi_by_id"]["labelled"], "answerable:", c["cogi_by_id"]["answerable"], "agreement", c["cogi_meta"]["rule_text_vs_id_agreement"])
    for s, title in (("labelled", "All questions with labels"), ("answerable", "The answerable")):
        print(f"\n**{title}, n = {cogi[s]['n']}: as it ships.** Coverage, then all-whole in brackets\n")
        print("| System | 1,000 | 2,500 | 5,000 |\n|---|---:|---:|---:|")
        print("| **Cogi** | " + " | ".join(f"{100 * cogi[s][b]['coverage']:.1f} ({100 * cogi[s][b]['whole']:.1f})" for b in BUDGETS) + " |")
        for name, label in SHIPPED.items():
            if name in r:
                print(f"| {label} | " + " | ".join(f"{cov(r[name], b, s=s):.1f} ({cov(r[name], b, 'whole', s):.1f})" for b in BUDGETS) + " |")
        for unit, title2 in (("message10", "generous, messages, top 10 sessions"), ("piece10", "generous, 256-token pieces, top 10 sessions")):
            print(f"\n**{title}, n = {cogi[s]['n']}: {title2}. Our construction.**\n")
            print("| From the ranking of | 1,000 | 2,500 | 5,000 |\n|---|---:|---:|---:|")
            print("| **Cogi as it ships, for reference** | " + " | ".join(f"{100 * cogi[s][b]['coverage']:.1f}" for b in BUDGETS) + " |")
            for name, label in RANKS.items():
                key = f"generous_{unit}_{name}"
                if key in r:
                    print(f"| {label} | " + " | ".join(f"{cov(r[key], b, s=s):.1f}" for b in BUDGETS) + " |")

    def paired(rows, s, heading):
        print(f"\n**{heading}, n = {cogi[s]['n']}**: points, Cogi minus row [95% interval]\n")
        print("| Row | 1,000 | 2,500 | 5,000 |\n|---|---|---|---|")
        for key, label in rows:
            if key in r:
                e = r[key][s]
                print(f"| {label} | " + " | ".join(f"{e[f'coverage@{b}']['cogi_minus_rival']:+.1f} [{e[f'coverage@{b}']['ci95'][0]:+.1f}, {e[f'coverage@{b}']['ci95'][1]:+.1f}]" for b in BUDGETS) + " |")

    ship = list(SHIPPED.items())
    gen = [(f"generous_message10_{k}", v) for k, v in RANKS.items()]
    piece = [(f"generous_piece10_{k}", v) for k, v in RANKS.items()]
    for s in ("labelled", "answerable"):
        paired(ship, s, "As it ships")
        paired(gen, s, "Generous, messages")
        paired(piece, s, "Generous, pieces")

    print("\n**Sensitivity, generous messages, labelled: top 5 / top 10 / top 20 sessions**\n")
    print("| From the ranking of | 1,000 | 2,500 | 5,000 |\n|---|---|---|---|")
    for name, label in RANKS.items():
        cells = []
        for b in BUDGETS:
            vals = [f"{cov(r[f'generous_message{k}_{name}'], b):.1f}" for k in (5, 10, 20) if f"generous_message{k}_{name}" in r]
            cells.append(" / ".join(vals))
        print(f"| {label} | " + " | ".join(cells) + " |")

    print("\n**Where Cogi's lead comes from, labelled, points.** Lead = native search + session ranking + pieces\n")
    print("| Rival | Budget | Cogi as it ships | Rival as it ships | Lead | Rival, same ranking, in pieces | Pieces and picker alone (rival gains) | Cogi's ranking, in pieces | Better session ranking | Cogi's own search within | ")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    control = r.get("generous_piece10_cogi-ranking")
    for ship_name, rank in PAIRS.items():
        pk = f"generous_piece10_{rank}"
        if ship_name not in r or pk not in r or not control:
            continue
        for b in BUDGETS:
            native = 100 * cogi["labelled"][b]["coverage"]
            s_ = cov(r[ship_name], b)
            p_ = cov(r[pk], b)
            c_ = cov(control, b)
            print(f"| {SHIPPED[ship_name]} | {int(b):,} | {native:.1f} | {s_:.1f} | {native - s_:+.1f} | {p_:.1f} | {p_ - s_:+.1f} | {c_:.1f} | {c_ - p_:+.1f} | {native - c_:+.1f} |")

    print("\n**Query time, ms, median / p95, and tokens used, median, labelled**\n")
    print("| System | 1,000 | 2,500 | 5,000 | Tokens used at each |\n|---|---:|---:|---:|---|")
    print("| **Cogi** | " + " | ".join(f"{cogi['labelled'][b]['query_ms_median']:.1f} / {cogi['labelled'][b]['query_ms_p95']:.1f}" for b in BUDGETS) + " | " + " / ".join(str(cogi['labelled'][b]['tokens_median']) for b in BUDGETS) + " |")
    for name, label in SHIPPED.items():
        if name in r:
            sm = r[name]["summary"]["labelled"]
            print(f"| {label} | " + " | ".join(f"{sm[b]['query_ms_median']:.1f} / {sm[b]['query_ms_p95']:.1f}" for b in BUDGETS) + " | " + " / ".join(str(sm[b]["tokens_median"]) for b in BUDGETS) + " |")
    print("\n**Rows that match or beat Cogi (point estimate at or above, or interval includes zero)**\n")
    for name, e in r.items():
        for s in ("labelled", "answerable"):
            for b in BUDGETS:
                x = e[s][f"coverage@{b}"]
                if x["cogi_minus_rival"] <= 0 or x["ci95"][0] <= 0:
                    print(f"{name} {s} {b}: rival {x['rival']} Cogi {x['cogi']} diff {x['cogi_minus_rival']:+.1f} [{x['ci95'][0]:+.1f}, {x['ci95'][1]:+.1f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
