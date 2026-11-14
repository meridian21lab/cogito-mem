# Cogi film factory: design

Date: 2026-11-13. Status: approved by delegation. Asked the open questions, the author answered "Do what you think is needed and best for project. Start with one film", so the builder's calls below stand until the author changes them.

## Intent

The author wants a series of short, funny, high-quality films that promote Cogi on YouTube Shorts and LinkedIn, and a "factory" that makes each new film mostly a matter of writing and staging, not engine work.

Episode 1 (Pillow frames, a narrator reading facts, mostly static scenes) was rejected: "the voice is not accurate, the animations are simple and unprofessional… dull, and maybe too techie". The author asked for creativity, humour and engagement, "more with Cogi" as an animated character, "more motion and dynamism", and "super high quality".

Who it is for: people who use or might use Claude Code, many of them not deep in the tech, scrolling a feed with the sound off. Success: the author calls a film awesome, and the next one doesn't need the engine touched.

## Decisions the author made

- **Format B:** a narrator tells the story while Cogi acts without speaking, as in a nature documentary meeting slapstick. The narrator voice must be "dynamic" and match the films.
- **Engine: Remotion** (React, rendered in headless Chrome), chosen over HyperFrames.
- **Voices from ElevenLabs.** The author is willing to pay for a plan. Upgrading is their step.
- **Build outputs live on the NAS** (`promo/nas.sh`), not on AWS, decided on 2026-11-13.
- **The author is happy to install tools** if they help.

## Approaches considered

| Approach | Trade-off | Outcome |
|---|---|---|
| Keep the Pillow engine and add craft (springs, transitions, captions, music) | Cheapest. But no anti-aliased vector shapes, glow, soft shadows or motion blur without a large rewrite, and the ceiling stays low | Dropped: it can't reach "super high quality" |
| HyperFrames (HTML + GSAP, Apache-2.0) | Free at any team size, and the best craft rulebook found. But it is 8 months old, its CLI sends telemetry, and it prefers HeyGen voices over ElevenLabs | Alternative; its rulebook is borrowed for our skill |
| **Remotion** (React) | Mature (since 2020). Packages for transitions, motion blur, word captions, light leaks, noise, Lottie, Rive, Three.js and ElevenLabs captions; Studio timeline for review; an official agent skill. Free for teams of 3 or fewer, otherwise $25/seat/month | **Chosen by the author** |

## Goals

1. **Cogi as an expressive silent character.** A puppet rig built from `site/assets/cogi.svg` and a reusable library of actions.
2. **A recurring cast and world** (the series bible below), so each film starts from known characters, places and props.
3. **A dynamic narrator** on ElevenLabs' newest model, with word timestamps so animation, sound and captions land on exact words.
4. **Designed sound:** a music bed, sound effects with a cause on screen, ducking under the voice, and a master at −14 LUFS with true peak at or below −1 dBTP.
5. **Captions that hold viewers:** one word highlighted at a time, large, inside the safe zones.
6. **Craft rules written down,** with numbers (motion, timing, camera, light, transitions, type, audio, hook), so quality doesn't depend on taste in the moment.
7. **A review loop the author can drive:** Remotion Studio to scrub and point at frames; contact sheets and automatic checks before the author sees anything.
8. **Two cuts per film from one source:** 9:16 for Shorts (1080×1920) and 4:5 for LinkedIn (1080×1350).
9. **The pilot:** remake "Claude forgets. Cogi doesn't." in the new style to prove the factory end to end.

## Non-goals

- A 3D Cogi, AI-generated video (Veo, Sora and the like), or a talking Cogi with lip sync.
- Publishing to YouTube or LinkedIn automatically. The author uploads by hand.
- A general video tool for other brands.

## Anti-goals: a failure even if it renders

- It looks templated or AI-generated: everything fades in, nothing has weight, the same transition every time.
- It is techie: jargon, commands on screen as the main visual, a list of features.
- It claims more than the README does (see "Product truth").
- It looks like an official Anthropic or Claude production (no Anthropic logos, no "Claude" mascot), or the narrator imitates a real, famous person.
- A stretch of more than about 3 s where nothing changes on screen.

## Series bible (proposal: the author can change any of it)

- **Premise of every film:** something important gets said, the assistant forgets it, and Cogi has kept it. Each film plays this premise from a different angle: one point, one proof.
- **Cogi:** silent, quick and proud. An obsessive collector of every word ever said, each one an acorn with a date on it. Protective of the hoard, delighted when a lost word is needed. Signature beats include:
  - catching a falling word-acorn mid-air;
  - stuffing its cheeks;
  - filing acorns in the hollow tree;
  - a smug tail flick when the right acorn is found;
  - presenting it with both paws.
- **The forgetful assistant, "Goldie" the goldfish:** cheerful, sincere and helpful, but with goldfish memory. Its bowl is the context window: when the bowl is refreshed or overflows, the memory swims away. Goldie is never mean or stupid, just forgetful, and is a stand-in for "your AI assistant", never drawn as Claude. A goldfish fits because "the memory of a goldfish" needs no explanation for non-technical viewers.
- **The developer:** seen only as hands, a mug and a laptop. A full human character is out of scope for the pilot.
- **The world:** a cosy desk at the edge of a forest. The laptop, Goldie's bowl and Cogi's hollow tree full of labelled acorns. Background trees and foreground leaves give depth.
- **The narrator:** an enthusiastic wildlife presenter who finds all this thrilling. Present tense, observational, short sentences, the jokes in timing and understatement. Says "your AI assistant" more than "Claude"; "Claude forgets. Cogi doesn't." is the series tagline.
- **The look:** flat 2D vector in Cogi's palette (cream, ink, orange) with depth from soft shadows, parallax layers, a light vignette, fine grain and an occasional light leak. Goldie needs a hue distinct from Cogi's orange.

## Product truth

Each film makes one point. The claims rules in today's `.claude/skills/cogi-promo-video/SKILL.md` stay in force:
- quote only what the README says;
- no token or cost savings, no reranker numbers, no "never forgets", no directory listing, no unmeasured pairings.

Numbers are rare and said plainly (for example "ninety-three times in a hundred, in over a million tokens of history"), shown big on screen, and sourced from the README at script time.

## How it works

### Per-film pipeline

1. **Brief** (`brief.md`): the one point and its proof, the premise angle, the comic engine, and 6–10 beats.
2. **Script** (`script` data): narration lines with ids. Each line carries cues: Cogi and Goldie actions, camera moves, sound effects and caption emphasis, anchored to words in the line. Roughly 90–130 words for a 35–50 s film.
3. **Author approval of the script before any paid voice generation.**
4. **Voice:** a script calls ElevenLabs text-to-speech with timestamps on the newest model available (`eleven_v4` today) with the series voice. It caches each line's audio and word timings, keyed by a hash of voice, model, settings and text, so only changed lines are paid for.
5. **Animatic:** scenes blocked in Remotion with the real voice, poses and camera; a contact sheet of stills, then the author scrubs it in Studio and gives feedback by timestamp.
6. **Animation pass:** actions, camera, transitions and light, then sound effects and music.
7. **Checks before the author sees a cut:**
   - automatic: stillness over 3 s, text sizes against the floors, safe zones per format, loudness, duration;
   - a reviewer subagent that sees only the contact sheet and a few frames, not the code, and names the weakest scene.
8. **Render both cuts,** normalise loudness in two passes, make the covers, and fill in `publish.md` (YouTube title, description and hashtags; LinkedIn caption, with links going in the first comment).
9. **Hand over, then archive:** the author uploads; accepted cuts go to the NAS with `promo/nas.sh`.

### The Cogi rig

- **Parts:** `cogi.svg` is 24 simple shapes. Group them into named parts with pivots:
  - tail (3 paths);
  - body and belly;
  - head (head, ears and inner ear, snout, eye and its highlight, nose, mouth, cheek);
  - paws;
  - acorn (nut, cap, stem);
  - feet;
  - ground shadow.
- **Driving it:** the rig is a React component driven by props (pose values per part), so actions are pure functions of the frame.
- **Base actions:**
  - idle breathing; blinks;
  - look-at (eye offset);
  - ear twitch; tail swish with follow-through;
  - head tilt; hop and land with squash and stretch;
  - startle; cheek stuff; present acorn; proud chest puff.
- **Poses the parts can't reach** (running, sleeping, digging) get new SVG drawings in the same style, each reviewed with the author before use.
- **Goldie** gets the same treatment: drawn as SVG parts (body, tail, fins, eye) with a small action set (swim loop, bubble, blink, the "forget" double-take).

### Formats

- **One source, two framings.** Compose at 1080×1920 and keep the key action inside a shared central 1080×1350 band, so the 4:5 cut is a reframing of the same film. Captions and the end card get their own placement per format.
- **YouTube's overlays (measured on a live Short):** the top ~9% (header, mute button), the bottom ~12% (channel and title) and the right edge from ~70% down (buttons). Nothing important goes there.

### Sound

- **Narrator:** the series voice (see "Settled by the builder").
- **Sound effects:** from ElevenLabs sound generation, cached like the voice.
  - about 6–10 per film, each caused by something on screen;
  - 3–6 dB above the music bed, landing one frame after their picture;
  - rotate 2–3 takes of any sound used more than once.
- **Music bed:** generated with ElevenLabs Music to the film's length.
  - about −18 dB under the voice, ducked 12–15 dB while the narrator speaks;
  - no energy that lives only below 150 Hz, since phone speakers lose it;
  - fades out before the call to action.
- **Master:** −14 LUFS integrated, true peak ≤ −1 dBTP, two-pass ffmpeg `loudnorm`, 30 ms fades at every audio boundary.

### The skill

- **Rewrite `.claude/skills/cogi-promo-video/`** into the factory's skill. It covers:
  - the series bible and story and comedy rules;
  - the product-truth rules and the per-film pipeline;
  - the craft rules with numbers and sources (from the 2026-11-13 research: HyperFrames' motion, captions and sound references; Remotion's skills; Material and NN/g timing; YouTube loudness);
  - the review checklist.
- **Install Remotion's official agent skills locally and don't commit them:** that repository has no licence file.

### Repo layout

- **`promo/` becomes a Remotion project:** shared kit, cast, films, scripts for voice, sound effects, checks and rendering, and `nas.sh`.
- **The Pillow kit and episode 1's sources are removed** once the pilot renders; git history keeps them.
- **Generated audio, renders, stills and caches stay out of git** and go to the NAS.

### Order of locking (builder's call, recorded here)

- **The series bible is approved before any cast or world art is drawn,** so the most expensive drawing and rigging isn't thrown away.
- **The narrator voice is locked before the pilot's animatic.** Cues, captions and sound effects sit on the voice's word timings, so a later voice change means re-timing and paying again.

## Constraints

- **Remotion's licence:** free only if the organisation making the videos has 3 people or fewer.
- **ElevenLabs:** a paid plan, for the commercial licence and for library voices. It was active by 2026-11-13.
  - The key can call library voices, text-to-speech with timestamps, sound generation and music.
  - It needs voice generation only if a custom narrator is ever designed.
- **The repo is public:** no secrets, no home-infrastructure details, no unlicensed third-party assets committed.
- **Local rendering on the author's Mac** (M5 Max, 48 GB, Node 24, ffmpeg).
- **Cost:** paid calls under $50 are pre-approved; anything larger is asked first.

## Left to the builder

- **Engineering details:**
  - Remotion version and package set;
  - file layout inside `promo/`;
  - how cues are written in the script data;
  - the rig's code structure and pivot values;
  - the check script.
- **Production details:**
  - which Remotion transitions and effects make the default set;
  - how the 4:5 reframing is computed;
  - the contact-sheet format;
  - the caching layout.

## Settled by the builder (the author delegated these on 2026-11-13)

- **Remotion licence:** assumed free, as meridian21lab is a team of 3 or fewer. The author confirms this before the first public upload; above 3 people it is $25 per seat per month.
- **Artwork:** the builder draws every character, prop and place as SVG in the logo's flat style. An illustrator comes in only if the pilot shows that style has hit its limit.
- **Series bible:** as proposed above: Goldie, the desk at the forest edge, the wildlife-presenter narrator.
- **Narrator:** "Alec – Nature Documentary Narrator" from the ElevenLabs library (`Ovio1nb5Thj5cZeW3MPS`) on `eleven_v4`.
  - Ten voices read the same audition line, using the v4 audio tags `[excited]`, `[whispers]` and `[pause]`. Alec's pitch varied the most: 8.7 semitones SD and 26 semitones across 90% of his range, against 5.5 and 17 for the runner-up, Cedric.
  - Runners-up: Cedric (`VvVVKaa2nHZpbZdtSRSX`) and Mark (`nrD2uNU2IUYtedZegcGx`). The author was sent all three.
  - Cues hang on word timings, so a voice change re-flows a film on its own. It costs a new voice take and a re-render, not re-animation.
- **"Cogi" is said KOH-ghee,** with a hard g, rhyming with "yogi", as in "cogito". A text alias in the voice script makes sure the narrator says it that way.
- **Music:** ElevenLabs Music. The plan is paid now: on 2026-11-13 library voices, sound generation and music all answered 200.
- **The key's permissions:** it still lacks `speech_to_text`, `voice_generation` and `user_read`. None of these is needed. A local Whisper transcription checks that the narration matches the script.
