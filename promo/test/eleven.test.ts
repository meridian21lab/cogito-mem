import {existsSync, mkdtempSync, readdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {describe, expect, it} from 'vitest';
import {cacheKey, writeAtomic} from '../scripts/lib/eleven';

describe('cacheKey', () => {
  const base = {text: 'Hi', voiceId: 'v', model: 'eleven_v4', settings: {stability: 0.4}};

  it('ignores key order', () => {
    expect(cacheKey(base)).toBe(cacheKey({settings: {stability: 0.4}, model: 'eleven_v4', voiceId: 'v', text: 'Hi'}));
  });

  it('changes when anything that shapes the audio changes', () => {
    const k = cacheKey(base);
    expect(cacheKey({...base, text: 'Hi!'})).not.toBe(k);
    expect(cacheKey({...base, voiceId: 'w'})).not.toBe(k);
    expect(cacheKey({...base, model: 'eleven_v3'})).not.toBe(k);
    expect(cacheKey({...base, settings: {stability: 0.5}})).not.toBe(k);
  });
});

describe('writeAtomic', () => {
  it('writes the file', () => {
    const dir = mkdtempSync(join(tmpdir(), 'cogi-'));
    writeAtomic(join(dir, 'a.txt'), 'x');
    expect(readdirSync(dir)).toEqual(['a.txt']);
  });

  it('leaves nothing behind when the data cannot be written', () => {
    const dir = mkdtempSync(join(tmpdir(), 'cogi-'));
    expect(() => writeAtomic(join(dir, 'b.txt'), undefined as unknown as string)).toThrow();
    expect(existsSync(join(dir, 'b.txt'))).toBe(false);
    expect(readdirSync(dir)).toEqual([]);
  });
});
