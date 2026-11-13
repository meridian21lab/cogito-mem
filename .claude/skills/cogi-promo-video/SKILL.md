---
name: cogi-promo-video
description: Make short narrated promo videos of Cogi (cogito-mem) for YouTube Shorts (9:16) and LinkedIn (4:5), about 45-60 s, with an ElevenLabs voiceover and burned-in captions, drawn frame by frame with Pillow and encoded with ffmpeg. Use when the user asks for a Cogi promo, a Short, a reel, a LinkedIn video, the next episode of the promo series, or to change or re-render one in promo/videos/.
---

# Cogi Promo Video

A promo video shows one thing Cogi does, in about a minute: a title card, 5-7 animated scenes, a voiceover and captions. Each one sends people to install Cogi or read the results. The engine, the squirrel and the fonts are in `promo/kit/`; each video is one folder in `promo/videos/`. The series plan is in `promo/README.md`.

This skill is adapted from the author's `explainer-video` skill in ksopyla-ai-blog (`.cursor/skills/explainer-video/`), which made episode 1. The narration, visual and Shorts rules below come from its revision rounds. When a rule here changes for a reason that also applies to blog videos, say so, so the author can port it.

## One Point Per Video

- **Each video makes one point** from the series plan, with one proof. Episode 1 is the overview; the rest go deeper on one thing each.
- **The story is a user's moment, not a feature list**: something you said is gone, Cogi brings it back. Episode 1's arc works: the problem in the first 3 seconds (the acorn demo), what Cogi is, why you can trust it, the proof, how to get it.
- **Close with one action**: the install command, or "see the results" with the site address on screen. The question for discussion belongs in the LinkedIn post text, not the video.

## What A Video May Claim

The README and the site are the marketing source, and every claim rests on data. Use only what they say today, in their words, and recheck the README before each new script, since numbers there change after evals.

Quotable now (README, release 0.3.0):
- Every message kept word for word, with its date; one folder on your computer; no account, no API key, no AI calls to save a message.
- LongMemEval's long test: about 480 past sessions, some 1.2 million tokens, per question; the right past session is among the first five for 93.0% of 500 questions, with no AI model involved, ahead of four other local memory plugins on the same questions (86.6-89.8% at their best settings).
- LoCoMo with GPT-5 mini answering: 1,000 tokens from Cogi answer 89.4% right against 94.1% from rereading the whole conversation, which is 95% of the quality from about 9 times fewer tokens.
- A search over 10 million tokens takes 26 ms on a laptop CPU.
- Install: `claude plugin install cogito-mem --marketplace meridian21lab/cogito-mem`, or the agent prompt in `site/install.md`.

Never claim:
- **Token or cost savings.** The eval has not run, so there is no number to quote.
- **Reranker numbers.** The plugin ships plain hybrid search.
- **That Claude "never forgets" or recalls everything by itself.** Automatic recall is far from complete; the honest line is that Claude can look back and gets your exact words. Episode 1's tip stands: "when it matters, ask Claude to check its memory".
- **A listing in Claude's plugin directory.** There isn't one.
- **Cogi plus Graphify gains.** The pairing has not been measured.
- Any number that is not in the README, or a rounder version of one ("over 90%" is fine for 93.0%, "nearly perfect" is not).

## Voice

The author's rules, from the blog videos:
- **Plain and specific, first person where it is his experience** ("I tested it on a public benchmark"). Modest, no hype words, no "revolutionary", no "In this video".
- **No AI-sounding copy**: no "Wrong question. The better one:" twists, no arrow-bullet slogans, no paired slogan endings. "Claude forgets. Cogi doesn't." is the series line; use it at most once per video.
- **Say exactly what is meant.** If a line is slightly off logically, he will correct it; get it right first.
- **His edits are final.** Keep his rewrites; adapt only for flow, say that you did, and offer his exact wording.

## Files

```
promo/
├── README.md                  # series plan, how to render, where files live
├── nas.sh                     # push / pull build outputs to the NAS
├── kit/
│   ├── video_kit.py           # engine: captions, TTS with caching, render, Shorts framing, CLI
│   ├── cogi_art.py            # the squirrel, rasterised from site/assets/cogi.svg, and the brand palette
│   └── fonts/                 # Outfit Bold, Work Sans (SIL OFL 1.1, licences beside them)
└── videos/<nn>-<slug>/
    ├── scenes.json            # title, size, fps, scenes [{id, visual, narration}]     (committed)
    ├── make_video.py          # one draw function per visual + make_cover()            (committed)
    ├── publish.md             # YouTube title/description/hashtags, LinkedIn caption   (committed)
    ├── <slug>.mp4, <slug>-shorts.mp4, cover*.jpg                                      (gitignored, NAS)
    ├── audio/                 # cached ElevenLabs clips + manifest                     (gitignored, NAS)
    ├── raw/                   # screen recordings, if any                              (gitignored, NAS)
    └── stills*/               # review PNGs                                            (gitignored)
```

Start a new video by copying the closest existing folder; `01-claude-forgets` is the reference for the brand look (cream page, ink text, orange accent, the squirrel, acorns as saved messages, a dark terminal).

## Requirements

- `uv` and `ffmpeg`/`ffprobe` on PATH (`brew install ffmpeg`).
- `ELEVENLABS_API_KEY` in the repo-root `.env` (`KEY=value` lines). Never print or commit it. The key is restricted: it can list voices and speak, but cannot read the credit balance, so check credits on the ElevenLabs site.
- Voice: the kit's default is George (`JBFqnCBsd6RMkjVDRZzb`, warm British storyteller), used in episode 1. Keep one voice across the series; to change it, set `ELEVENLABS_VOICE_ID` in `.env` and re-render every episode with `--regen`.

## Workflow

1. **Pick the episode** from `promo/README.md` and reread the README section it draws on.
2. **Write `scenes.json`** (narration rules below). Show the narration to the author before spending TTS credits.
3. **Draw the scenes** in `make_video.py`: `def scene_x(frame, t, dur, speech, sc)`, register it in `SCENES`, add `make_cover()`, end with `vk.run(HERE, SCENES, make_cover, "<slug>.mp4")`. The cover title is the video's hook.
4. **Review with stills**: `--stills` (and `--stills --shorts`) writes the cover and each scene at 35% and 95% of its length, with no TTS and no encoding. Paste them into one contact sheet and look at every scene at once: overlaps, empty stretches, text near the caption band.
5. **Render both cuts**: the default run makes the 4:5 LinkedIn video; `--shorts` makes the 9:16 Short from the same scenes. TTS is cached per scene by a hash of voice, model and narration, so the second cut costs nothing.
6. **QA each mp4**: `ffprobe` (h264 + aac; 1080x1350 and 1080x1920); frames at the narration cue points (`ffmpeg -ss <t> -i v.mp4 -frames:v 1 f.png`) to check each visual lands with its words; captions present throughout.
7. **Hand over**: send both mp4s and covers to the author with `publish.md` filled in. The author uploads; never post to his accounts.
8. **Keep it**: once the author accepts a cut, `bash promo/nas.sh push <video>` copies the videos, covers, voice clips and raw recordings to the NAS.

## Publishing Notes (publish.md)

- **YouTube Short**: title = the hook plus `#Shorts`; description with what Cogi is, the install command, the site, the repo and the results page; 3 hashtags including `#Shorts`. After upload: YouTube Studio → Subtitles → unpublish the automatic track, since the captions are burned in. A changed render means a new upload: YouTube cannot replace a video file.
- **LinkedIn**: upload the 4:5 mp4 natively and set the cover as the thumbnail; never post the YouTube link. Links go in the first comment, not the post.

## Narration Rules

- 5-7 scenes, at most ~28 words each, 120-150 words in total. George reads about 2.5 words/s and each scene adds a 0.4 s pause: 140 words is about 57 s. Aim under 60 s; Shorts allow up to 3 minutes, but under a minute keeps viewers to the end.
- Scene 1 is the hook: the problem within 3 seconds. Every sentence earns its place; no dangling references to things never said.
- Spoken English: short sentences, contractions fine. Write numbers as spoken ("ninety-three percent") so TTS reads them right, and show the figure on screen.
- One idea per scene.

## Visual Rules

- **Format**: 1080x1350 (4:5), 30 fps, H.264 + AAC. The title card is held for 1 s as the first frame, so the feed thumbnail is never black.
- **Layout**: visuals stay above `CONTENT_BOTTOM` (y=1060); captions centre at `CAPTION_Y` (y=1150), clear of the bottom ~10% where players draw their controls. Captions are burned in because both feeds autoplay muted.
- **Shorts**: the 4:5 frame is placed full width below a 175 px top band on a blurred cover. YouTube covers the top ~9% (header, mute pill, its own captions), the bottom ~12% (channel and title) and the right edge from ~70% down (Like/Comment/Share). Keep the top band empty and nothing important bottom-right.
- **One concrete metaphor per scene**, animated on its key phrase with `cue(narration, "phrase", default) * speech`. Cogi's: acorns are saved messages, the hollow is the store, the terminal is Claude Code, a grid of tiles is the history being searched.
- **On-screen text adds to the captions**: a header, labels, at most ~8 extra words per scene; numbers on screen exactly as the README states them.
- **Brand**: palette from `cogi_art.py` (`CREAM`, `INK`, `ACCENT`, `ACORN`, ...); set `vk.BG = CREAM` in each video. Fonts: Outfit Bold (`HEAD`), Work Sans (`BODY`), a system monospace (`mono`).
- **Fit text**: measure with `d.textlength` and shrink long lines; nothing within 50 px of the edges.

## Gotchas

- An overlay layer **replaces** pixels instead of blending them: a shape or text drawn with alpha 0 erases what is underneath. `text_c` skips zero-alpha text; guard shapes with `if a > 0`, and do not cross-fade two labels in the same spot.
- The bundled fonts lack some glyphs (✓, ↑): draw them (`check_mark`) or avoid them. "→", "…" and "–" work.
- Colour emoji need Apple Color Emoji (Mac) or Noto Color Emoji (Linux); `paste_emoji` draws nothing without them, so every scene must still read without emoji.
- Every animated value must be a pure function of `t`. Random layouts use a fixed seed (`random.Random(7)`), or they jump between frames.
- A render takes about a minute per cut on the Mac. Iterate with `--stills`, not full renders.
- `.env` lines must be `KEY=value`; the kit skips lines without `=`.
