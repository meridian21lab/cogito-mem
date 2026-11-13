import {describe, expect, it} from 'vitest';
import {stillRuns} from '../scripts/lib/still';

describe('stillRuns', () => {
  it('finds a 4 s hold', () => {
    const diffs = [...Array(30).fill(5), ...Array(120).fill(0.1), ...Array(30).fill(5)];
    const runs = stillRuns(diffs, 30, 0.5);
    expect(runs).toHaveLength(1);
    expect(runs[0].from).toBeCloseTo(1, 1);
    expect(runs[0].seconds).toBeCloseTo(4, 1);
  });

  it('ignores a picture that changes every 2 s', () => {
    const diffs = Array.from({length: 300}, (_, i) => (i % 60 === 0 ? 5 : 0.1));
    expect(stillRuns(diffs, 30, 0.5, 3)).toEqual([]);
  });
});
