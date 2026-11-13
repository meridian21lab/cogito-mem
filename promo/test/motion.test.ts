import {describe, expect, it} from 'vitest';
import type {Timeline} from '../src/kit/timeline';
import {blinkAt, duckedVolume, hop, keys, springAt} from '../src/kit/motion';

describe('springAt', () => {
  it('is 0 before it starts and settles at 1 within a second', () => {
    expect(springAt(10, 20, 30)).toBe(0);
    expect(Math.abs(springAt(50, 20, 30) - 1)).toBeLessThan(0.01);
  });

  it('overshoots on the way', () => {
    const peak = Math.max(...Array.from({length: 30}, (_, i) => springAt(20 + i, 20, 30)));
    expect(peak).toBeGreaterThan(1.02);
  });
});

describe('hop', () => {
  it('starts and ends on the ground, squashes on landing', () => {
    expect(hop(0, 0, 20, 100).y).toBe(0);
    expect(hop(20, 0, 20, 100).y).toBe(0);
    expect(hop(10, 0, 20, 100).y).toBeLessThan(-80);
    expect(hop(18, 0, 20, 100).squash).toBeLessThan(1);
    expect(hop(40, 0, 20, 100)).toEqual({y: 0, squash: 1});
  });
});

describe('keys', () => {
  it('holds the first and last values and interpolates between', () => {
    const track: [number, number][] = [[10, 0], [20, 100]];
    expect(keys(0, track)).toBe(0);
    expect(keys(30, track)).toBe(100);
    expect(keys(15, track)).toBeGreaterThan(0);
    expect(keys(15, track)).toBeLessThan(100);
  });
});

describe('blinkAt', () => {
  it('blinks now and then, and is open most of the time', () => {
    const v = Array.from({length: 300}, (_, f) => blinkAt(f, 1));
    expect(v.filter((x) => x > 0.9).length).toBeGreaterThan(2);
    expect(v.filter((x) => x === 0).length).toBeGreaterThan(250);
  });
});

describe('duckedVolume', () => {
  const tl = {fps: 30, lines: [{id: 'L1', from: 30, to: 90, file: '', words: []}], speaking: () => false} as unknown as Timeline;
  it('ducks 13 dB under the voice and sits at -18 dB in a long gap', () => {
    expect(duckedVolume(60, tl)).toBeCloseTo(10 ** (-31 / 20), 4);
    expect(duckedVolume(200, tl)).toBeCloseTo(10 ** (-18 / 20), 4);
  });
});
