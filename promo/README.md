# Cogi films

Short, funny promo films of Cogi for YouTube Shorts (9:16) and LinkedIn (4:5).

A wildlife-documentary narrator tells the story while two characters act it out:
- **Goldie the goldfish:** your AI assistant, cheerful and forgetful.
- **Cogi the squirrel:** keeps every word as a dated acorn and digs out the right one.

The films are made with Remotion (React rendered in headless Chrome). The voice, sound effects and music come from ElevenLabs. Every move is tied to a spoken word, so a new voice take re-flows the whole film.

The `cogi-promo-video` skill (`.claude/skills/cogi-promo-video/`) holds the rules:
- what a film may claim;
- the series bible;
- the craft rules (motion, camera, light, type, sound);
- the steps.

The design is in `docs/superpowers/specs/2026-11-13-cogi-film-factory-design.md`.

## The series

One point per film, each with one proof from the README.

| # | Working title | The one point | Proof | Status |
|---|---|---|---|---|
| 1 | Claude forgets. Cogi doesn't. | The goldfish forgets when the chat ends; Cogi keeps your exact words, with the date, on your computer, and gives them back | The acorn demo | Style accepted 2026-11-13; on the NAS |
| 2 | Your memory stays home | One folder on your computer: no account, no API key, no AI calls to save a message; `<private>` text is skipped (redaction left out: it goes by patterns) | README, "Private and free" and "Stores" | Made on 2026-11-13, awaiting the author's review |
| 3 | A needle in 1.2 million tokens | Finds the right past session in a huge history, ahead of four other local memory plugins, in milliseconds | 93.0% vs 86.6–89.8%; 26 ms over 10M tokens | Idea |
| 4 | Read nine times less | The 1,000 tokens Cogi hands back give 95% of the answer quality of rereading the whole conversation | LoCoMo: 89.4% vs 94.1% | Idea |
| 5 | "What did we decide about…?" | How to use it: ask Claude to check its memory | A real session, with permission | Idea |
| 6 | Gone from the context, not from Cogi | After a long session or a compaction, the early messages are still there word for word | README, "Claude can look back" | Idea |
| 7 | Install in a minute | macOS, Linux or Windows, or let Claude install it with the prompt from the site | `site/install.md` | Idea |

Recheck each number against the README before writing a script, since numbers change after evals.

## Make a film

From `promo/` (needs Node 24, `ffmpeg`, and `ELEVENLABS_API_KEY` in the repo-root `.env`):

```bash
npm install
cp -r src/films/01-claude-forgets src/films/02-stays-home   # then rewrite script.ts and Film.tsx, register it in src/Root.tsx
npm run voice -- 02-stays-home    # narration + word timings (cached: only changed lines are paid for)
npm run sfx -- 02-stays-home      # sound effects
npm run music -- 02-stays-home    # music bed, fitted to the film's length
npm run studio                    # scrub it in Remotion Studio
bash scripts/render.sh 02-stays-home   # both cuts, mastered to -14 LUFS, covers, contact sheets
npm run check -- 02-stays-home         # loudness, true peak, no still stretch > 3 s, length
npm test                               # the kit's unit tests
```

## Where the files live

| What | Where | Why |
|---|---|---|
| The kit, cast, world, film scripts and scenes, publish notes, fonts | Git, in `promo/` | Small text; they rebuild everything else |
| Voice, sound effects, music (`public/films/<film>/`) and renders (`out/<film>/`) | Your checkout, gitignored; kept on the NAS at `/nas/ml_data/cogito-mem/promo/films/<film>/` | Paid for or heavy |
| Published copies | YouTube and LinkedIn | The public versions |

The NAS is mounted on Odra, not on the Mac, so `nas.sh` copies over `ssh odra`:

```bash
bash promo/nas.sh push 01-claude-forgets    # once the author accepts a cut
bash promo/nas.sh pull 01-claude-forgets    # on a fresh checkout, so the audio isn't bought twice
bash promo/nas.sh ls
```

The rejected Pillow-drawn first version of episode 1 (2026-11-11) is archived on the NAS under `promo/videos/`, and its sources are in git history (commit 5bb3d0b).
