---
name: cogi-promo-video
description: Make short, funny, character-animated promo films of Cogi (cogito-mem) for YouTube Shorts (9:16) and LinkedIn (4:5) with the Remotion film factory in promo/. A wildlife-documentary narrator (ElevenLabs) tells the story while Cogi the squirrel and Goldie the goldfish act it out. Use when the user asks for a Cogi promo, a Short, a reel, a LinkedIn video, the next film of the series, or to change, re-voice or re-render one.
---

# Cogi Promo Films

The series runs on one joke: your AI assistant forgets, Cogi doesn't.
- **Goldie the goldfish** is the cheerful, forgetful assistant. Its bowl is the context window.
- **Cogi the squirrel** keeps every word as a dated acorn in its tree, and digs out the right one when it's needed.
- **An over-excited wildlife presenter** narrates it all.

Each film makes **one point with one proof**, in 35–50 s, and is funny first.

The factory is `promo/`, a Remotion (React) project. A film is two files: `script.ts` (narration, sounds, music) and `Film.tsx` (the scenes). Everything else is shared:
- the cast (`src/cast`: Cogi, Goldie, the cloud) and the world (`src/world`: the set, props such as winged chats and acorns, placards, a magnifier, a leaf umbrella and rain, and the shared title and end cards in `Ending.tsx`);
- the camera, captions, film finish, overlays, motion and sound (`src/kit`);
- the ElevenLabs scripts, checks and render (`scripts/`).

Read these before writing a film:
- `references/marketing-brief.md`: what Cogi is, who it's for, our values, benefits, tone, and film ideas by audience. Read it first.
- `references/series-bible.md`: who is who, the world, the running gags.
- `references/craft.md`: motion, camera, light, type and sound rules, with numbers.
- `src/films/01-claude-forgets/` and `src/films/02-stays-home/`: the reference films.

The design is in `docs/superpowers/specs/2026-11-13-cogi-film-factory-design.md`.

## Why it is built this way

The author rejected the first, Pillow-drawn episode as "dull, too techie", "simple and unprofessional", with a voice that wasn't right. They asked for creative, funny, engaging, dynamic films in "super high quality".

So:
- characters act instead of slides;
- a narrator with a dynamic voice tells the story;
- every beat is tied to a spoken word;
- quality comes from written craft rules and automatic checks, not from taste on the day.

## What a film may claim

The README is the marketing source. Recheck it before each script, because numbers change after evals.

Quotable now (README, release 0.3.0):
- **What it keeps:** every message, word for word, with its date, in one folder on your computer. No account, no API key, no AI calls to save a message. When something drops out of the conversation, Claude searches Cogi and gets your exact words back.
- **LongMemEval, long test:** about 480 past sessions and some 1.2 million tokens per question. The right past session is among the first five for 93.0% of 500 questions, with no AI model involved. That is ahead of four other local memory plugins on the same questions (86.6–89.8% at their best settings).
- **LoCoMo, with GPT-5 mini answering:** 1,000 tokens from Cogi answer 89.4% right, against 94.1% from rereading the whole conversation. That is 95% of the quality from about 9× fewer tokens.
- **Speed:** a search over 10 million tokens takes 26 ms on a laptop CPU.
- **One memory for your assistants:** Claude Code and Codex save into the same memory; past chats load from a claude.ai or ChatGPT data export.
- **Install:** `claude plugin install cogito-mem --marketplace meridian21lab/cogito-mem`, or the agent prompt in `site/install.md`. Free and open source (MIT).

Never claim:
- **Token or cost savings.** There is no measured number.
- **Reranker numbers.** The plugin ships plain hybrid search.
- **That Claude "never forgets"** or recalls everything by itself. "Claude forgets. Cogi doesn't." is the series tagline, said once per film. The honest mechanism is that Claude can look back and gets your exact words.
- **A listing in Claude's plugin directory.**
- **Cogi plus Graphify gains.**
- **Any number not in the README,** or a rounder version of one. "Ninety-three times in a hundred" is fine; "nearly always" is not.

Numbers are rare: at most one per film, said plainly by the narrator and shown big on screen.

## Brand safety

- Goldie is "your AI assistant", never drawn as Claude.
- No Anthropic or Claude logos, and no Claude mascot.
- Name "Claude" in narration only where the sentence needs it (the tagline, "Claude Code").
- The narrator is a character, never an imitation of a real person.

## Requirements

- **Node 24** and `npm install` in `promo/`. Remotion fetches its headless Chrome on the first render.
- **`ffmpeg` and `ffprobe`** on PATH.
- **`uv`**, for the local Whisper check.
- **`ELEVENLABS_API_KEY`** in the repo-root `.env`, as a `KEY=value` line. Never print or commit it.
  - The plan is paid (Starter): library voices, sound generation and music work.
  - Starter allows `mp3_44100_128` at most; 192 kbps needs Creator.
  - The key cannot read the balance, transcribe or design voices.
- **Remotion licence:** free while the team making the films is 3 people or fewer.

## Making a film

From `promo/`:

1. **Brief.** Pick the point from `promo/README.md` and reread the README section behind it. In a comment at the top of `script.ts`, write the point, the proof and the comic engine.
2. **Script.** Copy `src/films/01-claude-forgets/` to `src/films/<nn>-<slug>/` and rewrite `script.ts`:
   - lines with ids;
   - `gap` before each line (comic timing lives in the gaps);
   - v4 audio tags (`[excited]`, `[whispers]`) inside the text;
   - `aliases: {Cogi: 'Kogi'}`, so "Cogi" is said KOH-ghee, with a hard g;
   - the sound prompts, the music prompt and the cover word.

   About 80–110 words. Show the narration to the author before paying for the voice, unless they have said to go ahead.
3. **Voice, sounds and music** (cached by content hash, so only changed lines cost credits):
   ```bash
   npm run voice -- <film>
   npm run sfx -- <film>
   npm run music -- <film>    # after voice, so the bed fits the film's length
   ```
   The voice script refuses a line whose spoken words don't match its caption words.
4. **Hear it.** Run a local Whisper over the clips. Every line must come back as written, and "Cogi" as "Kogi" or "Cogi", never "Coji". The script lives in the session scratchpad: `uv run --with mlx-whisper`, with `HF_HUB_DISABLE_IMPLICIT_TOKEN=1` if a stale Hugging Face token gets in the way.
5. **Block, then animate** `Film.tsx`:
   - every beat takes its frame from `tl.word(lineId, word)`, never a hard-coded frame;
   - register the film in `src/Root.tsx`, which creates `<slug>-shorts` and `<slug>-feed`.

   Iterate with half-size drafts and a contact sheet:
   ```bash
   npx remotion render src/index.ts <slug>-shorts out/drafts/s.mp4 --scale=0.5
   bash scripts/sheet.sh out/drafts/s.mp4 out/drafts/sheet.jpg 1
   ```
   Look at the sheet yourself (Read the jpg). `npm run studio` opens Remotion Studio for scrubbing.
6. **Render and check:**
   ```bash
   bash scripts/render.sh <film>   # both cuts, two-pass loudnorm, covers, contact sheets
   npm run check -- <film>         # loudness -14 ±1 LUFS, true peak <= -1 dBTP, no still stretch > 3 s, 25-60 s
   ```
7. **Review.** Before the author sees a cut, give a fresh subagent only the contact sheets and a few full-size frames, not the code. Ask for the weakest scene, the first-2-second hook, phone readability, the 4:5 crop and brand risk. Fix what it finds that holds up.
8. **Hand over.**
   - Send the author both mp4s from `out/<film>/` and the covers.
   - Fill in `publish.md` beside the script (see below).
   - The author uploads; never post to their accounts.
9. **Keep it.** Once the author accepts a cut, run `bash promo/nas.sh push <film>`. It copies the renders and the paid audio to the NAS. On a fresh checkout, `bash promo/nas.sh pull <film>` brings the audio back, so it isn't paid for twice.

## Publishing notes (publish.md)

- **YouTube Short:**
  - The title is the hook plus `#Shorts`.
  - The description covers what Cogi is, the install command, the site, the repo and how it was tested. Use 3 hashtags, including `#Shorts`.
  - After upload, open Studio → Subtitles and unpublish the automatic track, because the captions are burned in.
  - A new render means a new upload.
- **LinkedIn:**
  - Upload the 4:5 mp4 natively, with the cover as the thumbnail.
  - Put links in the first comment, never in the post. The end card says so.

## Voice of the copy

The narrator is a character: enthusiastic, observational, present tense, short sentences, with the jokes in timing and understatement.

Copy the author writes or signs (`publish.md`, post text) follows the author's rules:
- plain and specific;
- no hype words;
- no "In this video";
- no AI-sounding twists ("Wrong question. The better one:");
- the author's edits are final.

## Gotchas

- **Every animated value is a pure function of the frame.** Use the helpers in `src/kit/motion.ts` and seeded `rand()`, never `Math.random()`.
- **SVG ids are global per frame.** Give each repeated `<defs>` id a unique suffix (the Bowl uses its x).
- **Sound-generation lengths must be 0.5–30 s.** Music needs `voice.json` first.
- **Remotion's `volume` is kept at 1 or below.** `Sound.tsx` scales every gain together and `render.sh` brings the master up to −14 LUFS.
- **The YouTube overlays cover the top 9%, the bottom 12% and the right edge from 70% down.** Captions sit at y 1450 in 9:16 and y 1165 in 4:5, inside both. In close-ups, check that props (signs, labels) don't land on the caption band.
- **The 4:5 cut shows only the central band** (y 285–1635 of the 9:16 frame). Anything above y ≈ 650 in world space falls out of it in a 2× close-up. Check `sheet-feed.jpg`.
- **Same colour, no outline, invisible.** The cast is drawn flat without outlines, so a part laid over a part of the same colour vanishes (Cogi's paws over its head). Give it a rim or a different shade there, and check close-ups at full size.
- **One render, many frames.** To inspect beats, render one half-size draft and cut frames out of it with ffmpeg (`select=eq(n\,F)`); launching many `remotion still` runs at once is far slower.
- **Reuse paid audio.** Cache keys don't include the film, so a sound or line with the same prompt or text as an earlier film can be copied from its `public/films/<film>/` folder instead of bought again (the tagline and end-card lines are shared).
- **This Homebrew ffmpeg has no `drawtext` filter.** The contact sheets carry no timestamps; read them as one frame per second, left to right.
