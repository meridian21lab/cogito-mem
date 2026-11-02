#!/bin/bash
# Copies the adapters from the worktree to where they run.
S=/Users/ksirg/devel/cogito-mem/.claude/worktrees/agent-a1f6d0361068c1fe3/scripts/rivals_m
B=/private/tmp/claude-501/-Users-ksirg-devel-cogito-mem/2f8e80c5-f08b-4456-93a3-d17ec6ff8ff3/scratchpad/rivals-m
cp "$S"/*.py "$S"/*.sh "$B/adapters/"
cp "$S/agentmemory_run.ts.txt" "$B/agentmemory/repo/benchmark/rivals_m.ts"
