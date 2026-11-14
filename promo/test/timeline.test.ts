import {describe, expect, it} from 'vitest';
import type {FilmScript, VoiceData} from '../src/kit/script';
import {buildTimeline} from '../src/kit/timeline';

const script: FilmScript = {
  id: 't',
  title: 'T',
  voice: {voiceId: 'v', model: 'm'},
  aliases: {},
  lines: [
    {id: 'L1', text: '[excited] Behold the assistant.', gap: 0.5},
    {id: 'L2', text: 'And poof. Gone.', gap: 1},
  ],
  tail: 2,
  sounds: {},
  music: {prompt: ''},
};

const voice: VoiceData = {
  L1: {file: 'a.mp3', duration: 2, words: [{text: 'Behold', start: 0.1, end: 0.6}, {text: 'the', start: 0.7, end: 0.8}, {text: 'assistant.', start: 1, end: 1.9}]},
  L2: {file: 'b.mp3', duration: 1.5, words: [{text: 'And', start: 0, end: 0.2}, {text: 'poof.', start: 0.3, end: 0.7}, {text: 'Gone.', start: 1, end: 1.4}]},
};

describe('timeline', () => {
  const tl = buildTimeline(script, voice, 30);

  it('places lines one after another with their gaps', () => {
    expect(tl.line('L1').from).toBe(15);
    expect(tl.line('L1').to).toBe(15 + 60);
    expect(tl.line('L2').from).toBe(15 + 60 + 30);
  });

  it('finds words as absolute frames', () => {
    expect(tl.word('L1', 'assistant')).toBe(15 + 30);
    expect(tl.word('L2', 'POOF')).toBe(105 + 9);
  });

  it('throws with the line and word when a cue word is missing', () => {
    expect(() => tl.word('L1', 'nope')).toThrow(/L1.*nope/);
    expect(() => tl.line('L9')).toThrow(/L9/);
  });

  it('knows when the narrator is speaking', () => {
    expect(tl.speaking(20)).toBe(true);
    expect(tl.speaking(90)).toBe(false);
  });

  it('total includes the tail', () => {
    expect(tl.total).toBe(105 + 45 + 60);
  });
});
