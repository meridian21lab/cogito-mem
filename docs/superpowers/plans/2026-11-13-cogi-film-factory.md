# Cogi film factory and pilot film: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `promo/` into a Remotion project that makes narrated, character-animated Cogi films, and make the pilot "Claude forgets. Cogi doesn't." with it, in a 9:16 and a 4:5 cut.

**Architecture:**
- A film is a script plus a React scene file.
- The script holds the narration lines, the sound prompts and the music prompt.
- Scripts call ElevenLabs, cache the clips and word timings in `promo/public/films/<film>/`, and a pure timeline turns those timings into frame numbers.
- Scenes hang every move, camera beat and sound effect on a word.
- Shared parts (camera, captions, film finish, sound, the cast and the world) live in `promo/src/kit`, `promo/src/cast` and `promo/src/world`, so the next film only writes a script and scenes.

**Tech Stack:**
- Remotion 4.0.539 (with `@remotion/cli`, `@remotion/fonts`, `@remotion/media-utils`), React 19.1.10, TypeScript 5.9.
- vitest 4.1.12 and tsx 4.23.15 for scripts and tests.
- ffmpeg for loudness and contact sheets.
- ElevenLabs: `eleven_v4` text-to-speech with timestamps, sound generation and music.

**Spec:** `docs/superpowers/specs/2026-11-13-cogi-film-factory-design.md`

## Global Constraints

- Every package is pinned to an exact version at least two weeks old: Remotion 4.0.539 for every `@remotion/*` package.
- **Narrator:** library voice `Ovio1nb5Thj5cZeW3MPS` ("Alec") on `eleven_v4`. The alias `Cogi → Kogi` is applied only to the text sent to TTS (KOH-ghee, hard g).
- **Canvas and cuts:** compose at 1080×1920 at 30 fps. The 4:5 cut is the central 1080×1350 band, which starts at y = 285.
- **YouTube safe zones:** keep important content out of the top 9%, the bottom 12%, and the right edge from 70% of the height down.
- **Sound:**
  - Master at −14 LUFS integrated, true peak ≤ −1 dBTP, two-pass `loudnorm`, with 30 ms fades at audio boundaries.
  - Music bed at about −18 dB, ducked 12–15 dB under the voice.
  - 6–10 sound effects, 3–6 dB over the bed, each one frame after the picture that causes it.
- **Pacing:** no stretch over 3 s without visible change.
- **Captions:** one highlighted word at a time, at least 64 px tall in 9:16.
- **Claims:** only what the README says. Never mention token or cost savings, reranker numbers, "never forgets", a directory listing, or unmeasured pairings.
- **Never commit:** no Anthropic or Claude logos, no Claude mascot, no imitation of a real person's voice. Never commit secrets, generated audio, renders, or Remotion's agent skills.
- **Git:** generated media goes under `promo/public/films/*/{voice,sfx,music}/` and `promo/out/`, which are gitignored and kept with `promo/nas.sh`.

## Review Focus

1. **A cue names a word the line doesn't say,** after a typo or a new voice take. The render must fail and name the line and the word, never put the cue at frame 0. Tested in Task 2.
2. **`[tags]` or the Cogi alias shift the word count** between the caption text and the spoken text. The voice script must refuse that line, so captions can't drift off their words. Tested in Task 2.
3. **The voice, model, settings or text change.** The cached clip must not be reused, and an unchanged line must not be paid for twice. Tested in Task 3.
4. **An ElevenLabs call fails** (quota, 4xx, network). The script must exit non-zero with the status and message, and leave no half-written cache file behind. Tested in Task 3.
5. **The final mix misses the loudness target,** or a still stretch runs over 3 s. `check` must fail with the measured numbers. Tested in Task 6.

---

### Task 1: Remotion project skeleton

**Files:**
- Create: `promo/package.json`, `promo/tsconfig.json`, `promo/remotion.config.ts`, `promo/vitest.config.ts`.
- Create: `promo/src/index.ts`, `promo/src/Root.tsx`, `promo/src/kit/formats.ts`, `promo/src/kit/theme.ts`.
- Move: `promo/kit/fonts/*` to `promo/public/fonts/`.
- Modify: `.gitignore` to ignore `promo/node_modules/`, `promo/out/`, `promo/public/films/*/voice/`, `promo/public/films/*/sfx/` and `promo/public/films/*/music/`.
- Test: `promo/test/formats.test.ts`.

**Interfaces:**
- Produces:
  - `FORMATS: Record<'shorts'|'feed', {width:number; height:number; bandTop:number; captionY:number}>`. Shorts are 1080×1920 with `bandTop` 0. Feed is 1080×1350 with `bandTop` 285.
  - `type FormatId = keyof typeof FORMATS`.
  - `theme` with the palette and the font family names `display` (Outfit 700) and `body` (Work Sans 400).
  - `loadFonts(): void`.

- [ ] Write `formats.test.ts`:
  - feed height + 2 × feed `bandTop` === shorts height;
  - both cuts' `captionY` map to the same world y.
- [ ] Run `npm test` in `promo/`. Expect FAIL (module missing).
- [ ] Implement `formats.ts` and `theme.ts`, install the packages, and register a placeholder composition in `Root.tsx`.
- [ ] Run `npm test` (PASS) and `npx remotion compositions src/index.ts`, which should list the placeholder.
- [ ] Commit.

### Task 2: Timeline from script and word timings

**Files:**
- Create: `promo/src/kit/script.ts` (types), `promo/src/kit/timeline.ts`, `promo/src/kit/words.ts`.
- Test: `promo/test/timeline.test.ts`, `promo/test/words.test.ts`.

**Interfaces:**
- Produces:
  - `type Line = {id:string; text:string; gap?:number}`. `text` may hold `[tags]`, and `gap` is the seconds of silence before the line (default 0.25).
  - `type FilmScript = {id:string; title:string; voice:{voiceId:string; model:string; settings?:Record<string,number>}; aliases:Record<string,string>; lines:Line[]; tail:number; sounds:Record<string,{prompt:string; seconds:number}>; music:{prompt:string}}`.
  - `type WordTiming = {text:string; start:number; end:number}`, in seconds within the line.
  - `type VoiceData = Record<string, {file:string; duration:number; words:WordTiming[]}>`.
  - `captionWords(text:string): string[]`: strips the `[tags]` and splits on spaces.
  - `ttsText(text:string, aliases:Record<string,string>): string`: keeps the tags and swaps whole-word aliases.
  - `alignmentToWords(chars:string[], starts:number[], ends:number[]): WordTiming[]`: drops bracketed tags.
  - `buildTimeline(script:FilmScript, voice:VoiceData, fps:number): Timeline` with:
    - `line(id).from`, `line(id).to` (frames);
    - `word(lineId, word, nth=0): number` (frame);
    - `total: number`;
    - `speaking(frame): boolean`.

- [ ] Write `words.test.ts`:
  - `captionWords('[excited] Behold! The AI assistant.')` equals `['Behold!','The','AI','assistant.']`;
  - `ttsText('Cogi digs.',{Cogi:'Kogi'})` equals `'Kogi digs.'`;
  - `alignmentToWords` on `"[whispers] Hi you"` returns 2 words with their times.
- [ ] Write `timeline.test.ts`:
  - line 2 starts at line 1's end + gap;
  - `word('L1','assistant')` equals the line's start plus that word's frame;
  - an unknown word throws `/L1.*nope/`;
  - `speaking()` is true inside a line and false in a gap;
  - `total` includes `tail`.
- [ ] Run (FAIL), implement, and run again (PASS). Words match case-insensitively with punctuation stripped.
- [ ] Commit.

### Task 3: ElevenLabs scripts with a cache

**Files:**
- Create: `promo/scripts/lib/eleven.ts`, `promo/scripts/voice.ts`, `promo/scripts/sfx.ts`, `promo/scripts/music.ts`.
- Test: `promo/test/eleven.test.ts`.

**Interfaces:**
- Consumes: `FilmScript`, `ttsText`, `captionWords`, `alignmentToWords` (Task 2).
- Produces:
  - `cacheKey(parts:unknown): string`: a short sha256 of stable JSON.
  - `post(path:string, body:object): Promise<Response>`: reads `ELEVENLABS_API_KEY` from the repo `.env` and never prints it. It throws `ElevenError(status, message)` on any status other than 2xx.
  - `writeAtomic(file:string, data:Buffer|string)`: writes to a temporary file, then renames it.
  - The scripts take the film id: `npm run voice -- 01-claude-forgets`. They write:
    - `public/films/<id>/voice/<lineId>-<key>.mp3` and `voice.json` (`VoiceData`);
    - `sfx/<name>-<key>.mp3` and `sounds.json`;
    - `music/bed-<key>.mp3` and `music.json` (file and seconds).
  - The voice script refuses a line whose spoken word count doesn't match `captionWords`.

- [ ] Write `eleven.test.ts`:
  - `cacheKey` is equal for objects with reordered keys, and differs when `text`, `voiceId`, `model` or `settings` change;
  - `writeAtomic` leaves no file behind when the write throws.
- [ ] Run (FAIL), implement, run (PASS).
- [ ] Run `npm run voice -- 01-claude-forgets` twice. The second run must say "cached" for every line and make no request.
- [ ] Commit.

### Task 4: Kit: camera, captions, finish, sound

**Files:**
- Create: `promo/src/kit/motion.ts`, `promo/src/kit/Camera.tsx`, `promo/src/kit/Captions.tsx`, `promo/src/kit/Finish.tsx`, `promo/src/kit/Sound.tsx`.
- Test: `promo/test/motion.test.ts`.

**Interfaces:**
- Consumes: `Timeline`, `FORMATS` and `theme`.
- Produces:
  - `motion.ts`, with pure functions of the frame:
    - `springAt(frame, from, fps, cfg?)` returns 0→1 with overshoot;
    - `ease(frame, [f0,f1], [v0,v1], easing?)`;
    - `keys(frame, [[f, v, easing?], ...])`, a keyframe track;
    - `wobble(frame, freq, amp, seed)`;
    - `hop(frame, from, dur, height)` returns `{y, squash}`;
    - `blinkAt(frame, seed)` returns 0..1;
    - `duckedVolume(frame, tl, {base:-18, duck:-13, attack:4, release:12})`, in linear gain.
  - `<Camera shot={{x,y,zoom,rot}} format>`: places the world. `<Layer depth>` gives parallax.
    - `whipBlur(frame)` returns a horizontal blur in px from the camera's speed.
  - `<Captions tl format>`: one word highlighted at a time, in groups of up to 3 words, popping in.
  - `<Finish>`: a vignette, animated grain, and an optional light leak `from`/`dur`.
  - `<Voice tl>` places each line's clip. `<Sfx name at volume?>` loads `sounds.json`. `<Music tl>` loads `music.json` with ducking and a fade-out before the call to action.

- [ ] Write `motion.test.ts`:
  - `springAt` is 0 before `from` and reaches 1 ± 0.01 by `from + 30`;
  - `hop` is at y 0 at both ends, and its squash is below 1 on landing;
  - `duckedVolume` is about 10^(−31/20) mid-line and about 10^(−18/20) in a long gap.
- [ ] Run (FAIL), implement, run (PASS).
- [ ] Commit.

### Task 5: Cast and world

**Files:**
- Create: `promo/src/cast/Cogi.tsx` (rig from `site/assets/cogi.svg`'s shapes), `promo/src/cast/Goldie.tsx`, `promo/src/cast/Acorn.tsx`.
- Create: `promo/src/world/Backdrop.tsx`, `promo/src/world/Desk.tsx` (desk, laptop and screen, hands, mug), `promo/src/world/Bowl.tsx`, `promo/src/world/Tree.tsx`, `promo/src/world/Particles.tsx`.
- Create: `promo/src/CastSheet.tsx`, a composition showing every pose.

**Interfaces:**
- Produces:
  - `CogiPose`: `{x,y,scale,flip,lean,squash,headRot,earL,earR,tail,eye:[x,y],blink,brow,cheek,mouth:'smile'|'open'|'o'|'smug',paws,acorn}`.
  - `<Cogi pose={Partial<CogiPose>} />`, where `x`,`y` is the point between the feet.
  - `idleCogi(frame, seed)` returns breathing, blinks, ear twitches and a tail swish, merged under the explicit pose values.
  - `GoldiePose`: `{x,y,scale,flip,tilt,swim,blink,blank,mouth:'smile'|'o'|'flat',sparkle}` and `<Goldie pose>`.
  - `<Bowl x y slosh level bubble?>`, `<Laptop typed:string caret newChat:number>`, `<Hands typing:number>`, `<Tree x y shelfAcorns:number stamp:number>`, `<Acorn label? spin>`.
- [ ] Render stills of `CastSheet` (`npx remotion still`) and check each pose by eye. Cogi must read as the logo, and Goldie must stay distinct from Cogi's orange.
- [ ] Commit.

### Task 6: Pilot film, checks and render

**Files:**
- Create: `promo/src/films/01-claude-forgets/script.ts`, `promo/src/films/01-claude-forgets/Film.tsx`.
- Create: `promo/scripts/check.ts`, `promo/scripts/render.sh`, `promo/scripts/sheet.sh`.
- Test: `promo/test/check.test.ts`.

**Interfaces:**
- Consumes: everything above.
- Produces:
  - Compositions `claude-forgets-shorts` and `claude-forgets-feed`, plus a cover still for each.
  - `stillRuns(diffs:number[], fps:number, threshold:number): {from:number; seconds:number}[]` in `check.ts`.
  - `npm run check -- <film>` exits non-zero on:
    - integrated loudness outside −14 ± 1 LUFS;
    - true peak above −1 dBTP;
    - a still run over 3 s;
    - a duration outside 25–60 s.
  - `bash scripts/render.sh <film>` writes `out/<film>/{shorts,feed}.mp4`, normalised in two passes, and `cover-{shorts,feed}.jpg`.

- [ ] Write `check.test.ts`:
  - `stillRuns` finds one run of 4 s in a series that holds still for 120 frames at 30 fps;
  - it finds none when the series changes every 60 frames.
- [ ] Run (FAIL), implement, run (PASS).
- [ ] Write `script.ts` (narration, sounds, music) and run `npm run voice`, `npm run sfx` and `npm run music`.
- [ ] Transcribe the voice clips with a local Whisper (`uv run --with mlx-whisper`). Every line must match `captionWords` apart from punctuation, and "Cogi" must come back with a hard g (Cogi/Kogi/Coggie, not Coji).
- [ ] Block every scene in `Film.tsx` on the timeline, then render a contact sheet with `bash scripts/sheet.sh`.
- [ ] Animate: actions, camera, transitions, light, sound effects and the music bed.
- [ ] Render both cuts and run `npm run check` (PASS).
- [ ] Get a reviewer subagent's read of the contact sheets alone (no code), and fix the weakest scene it names.
- [ ] Commit.

### Task 7: Skill, docs and clean-up

**Files:**
- Rewrite: `.claude/skills/cogi-promo-video/SKILL.md`, plus `references/craft.md` (motion, camera, light, transitions, type, sound, hook, with numbers) and `references/series-bible.md`.
- Modify: `promo/README.md` and `promo/nas.sh` (the paths `public/films/<film>/` and `out/<film>/`).
- Delete: `promo/kit/` and `promo/videos/` (git history keeps them).
- [ ] Check that `bash promo/nas.sh ls` still works. Push the pilot only once the author accepts a cut.
- [ ] Commit and push to `dev`.
