# Series bible

## The premise

Something important gets said. The assistant forgets it. Cogi has kept it. Every film plays this premise from a new angle, with one point and one proof.

## The cast

**Cogi** (`src/cast/Cogi.tsx`, built from the 24 shapes of `site/assets/cogi.svg`)
- **Character:** silent, quick and proud. An obsessive collector of every word ever said; each word is an acorn with a date tag. Protective of the hoard, and delighted when a lost word is needed.
- **Signature beats:**
  - catching an acorn mid-air with a hop;
  - stuffed cheeks;
  - filing acorns on the shelves of the hollow (date tags stamp in);
  - the smug look: half lid, smirk, raised brow, a tail flick;
  - digging with only its back and tail showing;
  - popping up to present the found acorn with both paws and sparkling eyes.
- **Pose controls:** lean, squash, lift, head, ears, tail and curl, eye look, blink, lid, brow, cheek, mouth (smile, smug, grin, open, o), paws (-1 wind-up, 0 chest, 1 present, 2 raised), and run.
- **New drawings:** poses the parts can't reach (sleeping, a full run cycle, digging from the front) need a new drawing in the same flat style, reviewed with the author.

**Goldie** (`src/cast/Goldie.tsx`)
- **Character:** the AI assistant. Cheerful, sincere and helpful, with the memory of a goldfish. Never mean, never stupid, never drawn as Claude.
- **Look:** yellow-gold, so it never reads as a second Cogi.
- **Signature beats:**
  - the proud flip on a compliment;
  - the eager wiggle;
  - the blank stare (tiny pupils, flat mouth) the moment something is forgotten;
  - confused circling;
  - a bonk on the glass;
  - happy sparkle eyes when the words come back.

**The cloud** (`src/cast/Cloud.tsx`, from film 02)
- **Character:** "someone else's cloud". A big, fluffy, smiling salesman, a little too eager. Never named after or styled like a real company; it stands for the generic idea, so the README's comparison table is the only source for what it asks for.
- **Signature beats:** gulping chats; popping up placards ("Sign up!", "API key?"); reading glasses and a magnifier ("an AI to read it all"); a shocked "o" when refused; turning grey, frowning and raining on Cogi; puffing its cheeks and huffing off.
- **Pose controls:** tilt, squash, look, blink, mouth (grin, smile, open, frown, o) and how wide it opens, brow, grump, glasses, grey, puff. `CloudArm` draws a puffy arm to whatever it holds.

**The developer** is seen only as hands, sleeves, a laptop and a mug. The developer is "you".

## The world

A cosy desk at the edge of a forest:
- the laptop, with a generic chat window (orange bubble = you, sand bubble = the assistant);
- Goldie's bowl, which is the context window: a new chat swirls it and pops what was in it;
- a mug with an acorn on it;
- Cogi's tree right at the desk's end. Its hollow is level with the desk top and holds shelves of dated acorns. A wooden sign on the tree says "your computer", because that is where everything stays.

Behind them are parallax layers: sky with a warm sun at the top left, far tree line, mid trees, ground. Leaves drift through the foreground.

## The narrator

An enthusiastic wildlife presenter who finds all this thrilling. Present tense, observational, short sentences; the jokes live in timing and understatement.
- **Voice:** "Alec – Nature Documentary Narrator" from the ElevenLabs library (`Ovio1nb5Thj5cZeW3MPS`) on `eleven_v4`, with `[excited]` and `[whispers]` tags. Runners-up: Cedric (`VvVVKaa2nHZpbZdtSRSX`) and Mark (`nrD2uNU2IUYtedZegcGx`).
- **"Cogi"** is KOH-ghee, with a hard g; the alias `Cogi → Kogi` makes sure of it.
- **Naming:** say "your AI assistant" more than "Claude".

## Running gags and devices

- **Species cards (lower third, top left):** "The AI assistant, *Carassius forgetfulus*", "The squirrel, *Sciurus archivus*", "The chat, *Garrulus migratorius*" and "The cloud, *Cumulus signupensis*". Each new character gets mock Latin.
- **The rebel acorn:** one acorn on the shelf keeps growing wings and trying to leave; Cogi catches it every time (film 02 ends with Cogi chomping it into its cheek without even looking).
- **The brass plate** "~/.cogito-mem" over the hollow, under the "your computer" sign: the real folder, shown once it matters.
- **Paws over the eyes** (`cover` pose): Cogi not looking at what you marked private.
- **The binocular iris** opens a film.
- **Cogi's tail wipe** is the transition into the title card.
- **A lone cricket** fills the silence after something is forgotten.
- **The tagline** "Claude forgets. Cogi doesn't.", once per film: "Claude forgets." floats away word by word, "Cogi doesn't." slams in orange, and Cogi puffs up.
- **The end card:** "Cogi", "Free, open-source memory for Claude Code", and "Link in the description" (Shorts) or "Link in the first comment" (LinkedIn).
