// The film's clock: lines laid end to end with their gaps, and every word as an absolute frame.
// Scenes hang all motion, camera and sound on tl.word(line, word), so a new voice take re-flows the film.
import type {FilmScript, VoiceData} from './script';
import {captionWords, normWord} from './words';

export type TimedLine = {id: string; from: number; to: number; file: string; words: {text: string; from: number; to: number}[]};

export type Timeline = {
  fps: number;
  lines: TimedLine[];
  total: number;
  line: (id: string) => TimedLine;
  /** Frame where the nth (0-based) occurrence of `word` in line `id` starts. Throws if it is not said. */
  word: (id: string, word: string, nth?: number) => number;
  /** Frame where that word ends. */
  wordEnd: (id: string, word: string, nth?: number) => number;
  speaking: (frame: number) => boolean;
};

export const buildTimeline = (script: FilmScript, voice: VoiceData, fps: number): Timeline => {
  let cursor = 0;
  const lines: TimedLine[] = script.lines.map((l) => {
    const v = voice[l.id];
    if (!v) throw new Error(`No voice for line ${l.id}: run npm run voice -- ${script.id}`);
    const shown = captionWords(l.text);
    const from = cursor + Math.round((l.gap ?? 0.25) * fps);
    const to = from + Math.round(v.duration * fps);
    cursor = to;
    return {
      id: l.id,
      from,
      to,
      file: v.file,
      words: v.words.map((w, i) => ({text: shown[i] ?? w.text, from: from + Math.round(w.start * fps), to: from + Math.round(w.end * fps)})),
    };
  });
  const byId = new Map(lines.map((l) => [l.id, l]));
  const line = (id: string) => {
    const l = byId.get(id);
    if (!l) throw new Error(`No line ${id} in ${script.id}`);
    return l;
  };
  const find = (id: string, word: string, nth = 0) => {
    const hits = line(id).words.filter((w) => normWord(w.text) === normWord(word));
    if (!hits[nth]) throw new Error(`Line ${id} does not say "${word}" (occurrence ${nth}): ${line(id).words.map((w) => w.text).join(' ')}`);
    return hits[nth];
  };
  return {
    fps,
    lines,
    total: cursor + Math.round(script.tail * fps),
    line,
    word: (id, word, nth) => find(id, word, nth).from,
    wordEnd: (id, word, nth) => find(id, word, nth).to,
    speaking: (frame) => lines.some((l) => frame >= l.from && frame < l.to),
  };
};
