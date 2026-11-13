# Promo videos

Short narrated videos of Cogi for YouTube Shorts and LinkedIn: about a minute each, an ElevenLabs voice, captions burned in. Each video is drawn from code, so a changed line means a re-render, not a re-edit.

The `cogi-promo-video` skill (`.claude/skills/cogi-promo-video/`) holds the rules: what a video may claim, the voice, the layout, and the steps.

## The series

One point per video, each with one proof from the README. Episode 1 is the overview, and the rest go deeper.

| # | Working title | The one point | Proof | Status |
|---|---|---|---|---|
| 1 | Claude forgets. Cogi doesn't. | The acorn demo, then what Cogi is, why it is safe, how it was tested, how to install it | 93.0% top five at 1.2M tokens | Made on 2026-11-11 |
| 2 | Your memory stays home | One folder on your computer: no account, no API key, no AI calls to save a message. Common secrets are redacted and `<private>` text is skipped | README, "Private and free" and "Stores" | Idea |
| 3 | A needle in 1.2 million tokens | Finds the right past session in a huge history, ahead of four other local memory plugins, in milliseconds | 93.0% vs 86.6–89.8%; 26 ms over 10M tokens | Idea |
| 4 | Read nine times less | The 1,000 tokens Cogi hands back give 95% of the answer quality of rereading the whole conversation | LoCoMo: 89.4% vs 94.1% | Idea |
| 5 | "What did we decide about…?" | How to use it: ask Claude to check its memory, with a real recall from a real session (with permission), the growth plan's "Cogi remembers…" | A real session | Idea |
| 6 | Gone from the context, not from Cogi | After a long session or a compaction, the early messages are still there word for word | README, "Claude can look back" | Idea |
| 7 | Install in a minute | macOS, Linux or Windows, or let Claude install it with the prompt from the site | `site/install.md` | Idea |

Recheck each number against the README before writing a script: numbers change after evals.

## Make a video

From the repo root:

```bash
mkdir promo/videos/02-stays-home   # start from the closest video's sources, then rewrite them
cp promo/videos/01-claude-forgets/{scenes.json,make_video.py,publish.md} promo/videos/02-stays-home/
uv run --with Pillow promo/videos/02-stays-home/make_video.py --stills   # review PNGs, no voice, no encoding
uv run --with Pillow promo/videos/02-stays-home/make_video.py            # 4:5 cut for LinkedIn
uv run --with Pillow promo/videos/02-stays-home/make_video.py --shorts   # 9:16 cut for YouTube Shorts
```

Needs `uv`, `ffmpeg` and `ELEVENLABS_API_KEY` in the repo-root `.env`. The voice is George (ElevenLabs' `JBFqnCBsd6RMkjVDRZzb`) across the series; voice clips are cached per scene, so only changed lines are paid for again.

## Where the files live

| What | Where | Why |
|---|---|---|
| Scripts, narration, publish notes, kit, fonts | Git, in `promo/` | Small text; they rebuild everything else |
| Rendered videos, covers, voice clips, raw recordings | The NAS, `/nas/ml_data/cogito-mem/promo/videos/<video>/` | Large or paid for; plenty of room, no cost |
| Review stills | Your checkout only | Remade in seconds |
| Published copies | YouTube and LinkedIn | The public versions |

The NAS is mounted on Odra, not on the Mac, so `nas.sh` copies over `ssh odra`:

```bash
bash promo/nas.sh push                      # every video's build outputs to the NAS
bash promo/nas.sh pull 01-claude-forgets    # back to a fresh checkout, so voice clips aren't bought twice
bash promo/nas.sh ls
```

AWS S3 isn't used: the files are small, the NAS is free, and the public copies already live on YouTube and LinkedIn. S3 would earn its place if drafts needed sharing by link with people outside the house, or if renders ran in cloud sessions.
