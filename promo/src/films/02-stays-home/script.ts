// Film 02: "Your memory stays home."
// One point: Cogi keeps your memory in one folder on your own computer. No account, no API key, no AI calls
// to save a message; text marked <private> is skipped.
// Proof: README, "Private and free" and "What Cogi runs, downloads and stores" (Stores, Sends).
// Comic engine: a wildlife presenter narrates "the great migration" of chats to a pushy, smiling cloud, and the
// one squirrel who won't let a single acorn leave home. The cloud sulks; Cogi doesn't care.
// Claims: the cloud is "a memory tool's cloud", generic (no product named), so it never reads as Claude itself;
// its asks are the README's comparison table (account or API key, AI calls to store). "Your memory never leaves
// your machine" is about Cogi's copy (README: "Nothing leaves your machine"; Claude Code itself still talks to
// its model). <private> text is "not kept", not "not read". Redaction is not claimed: it goes by patterns.
import type {FilmScript} from '../../kit/script';

export const script: FilmScript = {
  id: '02-stays-home',
  title: 'Your memory stays home.',
  voice: {voiceId: 'Ovio1nb5Thj5cZeW3MPS', model: 'eleven_v4'}, // "Alec – Nature Documentary Narrator"
  aliases: {Cogi: 'Kogi'}, // KOH-ghee, hard g
  lines: [
    {id: 'hook', text: '[excited] Behold! The great migration.', gap: 0.15},
    {id: 'chats', text: "Your chats, flying off... to a memory tool's cloud.", gap: 0.25},
    {id: 'asks', text: '[whispers] Where it wants an account... an API key...', gap: 0.3},
    {id: 'reads', text: 'and an AI to read it all.', gap: 0.1},
    {id: 'home', text: "[excited] But Cogi's acorns never leave home.", gap: 0.8},
    {id: 'folder', text: 'Every word stays in one folder, on your own computer.', gap: 0.35},
    {id: 'nos', text: 'No account. No API key. No AI calls to save a message.', gap: 0.4},
    {id: 'private', text: "[whispers] And anything you mark private... Cogi won't keep a word.", gap: 0.6},
    {id: 'sulk', text: 'The cloud is... not thrilled.', gap: 0.7},
    {id: 'nothing', text: 'Your memory never leaves your machine. Not one acorn.', gap: 1.1},
    {id: 'tagline', text: "[excited] Claude forgets. Cogi doesn't.", gap: 0.6},
    {id: 'cta', text: 'Free, open-source memory for Claude Code.', gap: 0.45},
  ],
  tail: 1.6,
  sounds: {
    // shared with film 01 (same prompt, same cached file)
    whoosh: {prompt: 'quick cartoon whoosh, a short swish of air passing the camera', seconds: 0.7, takes: 3},
    type: {prompt: 'fast light typing on a laptop keyboard, soft clicky keys, close up', seconds: 1.6},
    pop: {prompt: 'soft cartoon bubble pop, small and playful', seconds: 0.5},
    catch: {prompt: 'cartoon catch, a soft thwip as a small acorn lands in paws', seconds: 0.5, takes: 3},
    ding: {prompt: 'bright magical sparkle chime, a small triumphant ding', seconds: 1.2},
    // new for film 02
    flap: {prompt: 'a flock of small cartoon wings flapping past, light fluttery paper wings, comedic', seconds: 2},
    gulp: {prompt: 'big soft cartoon gulp, a fluffy cloud swallowing something, comedic', seconds: 0.8},
    boing: {prompt: 'cartoon sign springing up with a short springy boing', seconds: 0.5, takes: 3},
    swat: {prompt: 'cartoon tail swat, a fast swish and a light cardboard thwack', seconds: 0.6, takes: 3},
    poof: {prompt: 'tiny magic poof, a small puff of smoke vanishing, soft and quick', seconds: 0.7},
    rain: {prompt: 'small comedic rain shower falling on a big leaf, close, gentle pitter patter', seconds: 3.5},
    rumble: {prompt: 'tiny sulky cartoon thunder grumble, small and comedic, not scary', seconds: 1.4},
    huff: {prompt: 'cartoon offended huff, a big puff of air blown out in a sulk', seconds: 0.8},
  },
  music: {
    prompt:
      'Playful orchestral comedy underscore for a cartoon nature documentary about a stubborn homebody squirrel. Pizzicato strings, marimba, oboe and bassoon, woodblock and light brushed percussion. Opens airy and wondering like a grand migration scene, turns sneaky and cheeky in the middle, a short mock-gloomy minor passage, then a sunny, bouncy, triumphant final phrase that resolves cleanly at the very end. 104 BPM, instrumental, no vocals, bright mid-range, light bass.',
  },
};
