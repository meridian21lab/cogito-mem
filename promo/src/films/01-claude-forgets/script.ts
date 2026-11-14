// Film 01, the pilot: "Claude forgets. Cogi doesn't."
// One point: your assistant forgets between chats; Cogi keeps your exact words and gives them back.
// Comic engine: an over-excited wildlife presenter narrates a goldfish (the assistant) and a squirrel (Cogi).
// Claims (README): Cogi keeps every message word for word with the time, locally; Claude gets exact words back;
// free and open source. Nothing else is claimed.
import type {FilmScript} from '../../kit/script';

export const script: FilmScript = {
  id: '01-claude-forgets',
  title: "Claude forgets. Cogi doesn't.",
  voice: {voiceId: 'Ovio1nb5Thj5cZeW3MPS', model: 'eleven_v4'}, // "Alec – Nature Documentary Narrator"
  aliases: {Cogi: 'Kogi'}, // KOH-ghee, hard g
  lines: [
    {id: 'hook', text: '[excited] Behold! The AI assistant.', gap: 0.15},
    {id: 'brilliant', text: 'Brilliant. Helpful.', gap: 0.2},
    {id: 'goldfish', text: '[whispers] And with the memory of... a goldfish.', gap: 0.25},
    {id: 'tell', text: '[excited] You tell it something important.', gap: 0.7},
    {id: 'ends', text: 'Then the chat ends...', gap: 1.2},
    {id: 'poof', text: 'and... poof. Gone.', gap: 0.2},
    {id: 'watch', text: '[whispers] But watch the squirrel.', gap: 1.1},
    {id: 'catches', text: '[excited] Cogi catches every word you two say...', gap: 0.35},
    {id: 'files', text: 'and files it away, with the date, right on your own computer.', gap: 0.15},
    {id: 'lost', text: 'Next chat. The goldfish is lost again.', gap: 0.6},
    {id: 'digs', text: 'But Cogi digs... and digs... and there it is!', gap: 0.5},
    {id: 'exact', text: 'The exact words, back where they belong.', gap: 0.5},
    {id: 'tagline', text: "[excited] Claude forgets. Cogi doesn't.", gap: 0.6},
    {id: 'cta', text: 'Free, open-source memory for Claude Code.', gap: 0.45},
  ],
  tail: 1.6,
  sounds: {
    whoosh: {prompt: 'quick cartoon whoosh, a short swish of air passing the camera', seconds: 0.7, takes: 3},
    type: {prompt: 'fast light typing on a laptop keyboard, soft clicky keys, close up', seconds: 1.6},
    pop: {prompt: 'soft cartoon bubble pop, small and playful', seconds: 0.5},
    blub: {prompt: 'single cute underwater bubble blub from a small fish', seconds: 0.6, takes: 2},
    swirl: {prompt: 'comedic water swirl and gurgle in a small fishbowl', seconds: 1.3},
    cricket: {prompt: 'a lone cricket chirping in an awkward silence, comedic, dry', seconds: 1.6},
    catch: {prompt: 'cartoon catch, a soft thwip as a small acorn lands in paws', seconds: 0.5, takes: 3},
    stamp: {prompt: 'rubber stamp thump on paper, crisp', seconds: 0.5, takes: 3},
    dig: {prompt: 'frantic cartoon rummaging and digging through dry leaves and wood, comedic', seconds: 2},
    ding: {prompt: 'bright magical sparkle chime, a small triumphant ding', seconds: 1.2},
    plop: {prompt: 'small acorn plops into a glass fishbowl, gentle water splash', seconds: 0.8},
  },
  music: {
    prompt:
      'Playful, curious orchestral comedy underscore for a cartoon nature documentary. Pizzicato strings, marimba, bassoon and clarinet, light brushed percussion. Starts sneaky and mischievous, builds bouncy energy in the middle, lifts into a warm, triumphant final phrase that resolves cleanly at the very end. 108 BPM, instrumental, no vocals, bright mid-range, light bass.',
  },
};
