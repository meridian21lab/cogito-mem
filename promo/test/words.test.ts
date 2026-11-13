import {describe, expect, it} from 'vitest';
import {alignmentToWords, captionWords, normWord, ttsText} from '../src/kit/words';

describe('words', () => {
  it('captionWords strips audio tags', () => {
    expect(captionWords('[excited] Behold! The AI assistant.')).toEqual(['Behold!', 'The', 'AI', 'assistant.']);
    expect(captionWords('Brilliant. [whispers] And... a goldfish.')).toEqual(['Brilliant.', 'And...', 'a', 'goldfish.']);
  });

  it('ttsText swaps whole-word aliases and keeps tags', () => {
    expect(ttsText('Cogi digs.', {Cogi: 'Kogi'})).toBe('Kogi digs.');
    expect(ttsText("[excited] Cogi's acorn", {Cogi: 'Kogi'})).toBe("[excited] Kogi's acorn");
    expect(ttsText('Cogito', {Cogi: 'Kogi'})).toBe('Cogito');
  });

  it('normWord ignores case and punctuation', () => {
    expect(normWord('Acorn!')).toBe('acorn');
    expect(normWord("doesn't.")).toBe("doesn't");
  });

  it('alignmentToWords drops bracketed tags and keeps word times', () => {
    const text = '[whispers] Hi you';
    const chars = [...text];
    const starts = chars.map((_, i) => i * 0.1);
    const ends = chars.map((_, i) => i * 0.1 + 0.1);
    const words = alignmentToWords(chars, starts, ends);
    expect(words.map((w) => w.text)).toEqual(['Hi', 'you']);
    expect(words[0].start).toBeCloseTo(1.1);
    expect(words[0].end).toBeCloseTo(1.3);
    expect(words[1].start).toBeCloseTo(1.4);
  });
});
