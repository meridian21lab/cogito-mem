import {describe, expect, it} from 'vitest';
import {FORMATS, toWorldY} from '../src/kit/formats';

describe('formats', () => {
  it('feed is the central band of shorts', () => {
    expect(FORMATS.feed.height + 2 * FORMATS.feed.bandTop).toBe(FORMATS.shorts.height);
    expect(FORMATS.feed.width).toBe(FORMATS.shorts.width);
  });

  it('captions sit at the same world height in both cuts', () => {
    expect(toWorldY('shorts', FORMATS.shorts.captionY)).toBe(toWorldY('feed', FORMATS.feed.captionY));
  });

  it('shorts captions avoid the YouTube overlays', () => {
    const {height, captionY} = FORMATS.shorts;
    expect(captionY).toBeGreaterThan(height * 0.09);
    expect(captionY).toBeLessThan(height * 0.88 - 120);
  });
});
