// Turning script text into what is spoken, shown and timed.
// A line's text may carry ElevenLabs v4 audio tags like [excited]; they steer the voice and are never shown.
import type {WordTiming} from './script';

const TAG = /\[[^\]]*\]/g;

/** The words captions show, in order: the text without its [tags]. */
export const captionWords = (text: string): string[] => text.replace(TAG, ' ').split(/\s+/).filter(Boolean);

/** The text sent to TTS: tags kept, whole-word aliases swapped (Cogi -> Kogi for the hard g). */
export const ttsText = (text: string, aliases: Record<string, string>): string =>
  Object.entries(aliases).reduce((t, [from, to]) => t.replace(new RegExp(`\\b${from}\\b`, 'g'), to), text);

/** A word as cues match it: lower case, no punctuation except inner apostrophes. */
export const normWord = (w: string) => w.toLowerCase().replace(/[^\p{L}\p{N}']+/gu, '').replace(/^'+|'+$/g, '');

/** ElevenLabs character alignment -> words with start/end seconds, skipping [tags]. */
export const alignmentToWords = (chars: string[], starts: number[], ends: number[]): WordTiming[] => {
  const words: WordTiming[] = [];
  let inTag = false;
  let cur: WordTiming | null = null;
  chars.forEach((c, i) => {
    if (c === '[') inTag = true;
    if (inTag || /\s/.test(c)) {
      if (cur) words.push(cur);
      cur = null;
      if (c === ']') inTag = false;
      return;
    }
    if (!cur) cur = {text: '', start: starts[i], end: ends[i]};
    cur.text += c;
    cur.end = ends[i];
  });
  if (cur) words.push(cur);
  return words;
};
