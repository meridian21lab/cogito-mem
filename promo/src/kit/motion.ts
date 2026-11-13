// Motion primitives: pure functions of the frame, so any frame renders the same on its own.
// Defaults follow the craft rules: springy overshoot for arrivals, ease-out for moves, anticipation and
// squash/stretch for hops, nothing linear unless it is a constant drift.
import {noise2D} from '@remotion/noise';
import {Easing, interpolate, spring, type SpringConfig} from 'remotion';
import type {Timeline} from './timeline';

export const EASE = {
  out: Easing.bezier(0.22, 1, 0.36, 1),
  inOut: Easing.bezier(0.65, 0, 0.35, 1),
  in: Easing.bezier(0.55, 0, 1, 0.45),
  back: Easing.bezier(0.34, 1.56, 0.64, 1),
  linear: Easing.linear,
};

const SNAPPY: Partial<SpringConfig> = {damping: 11, stiffness: 180, mass: 0.7};

/** 0 -> 1 spring starting at `from`, with a little overshoot. */
export const springAt = (frame: number, from: number, fps: number, cfg: Partial<SpringConfig> = SNAPPY) =>
  frame < from ? 0 : spring({frame: frame - from, fps, config: cfg});

/** Clamped interpolation between two frames, ease-out by default. */
export const ease = (frame: number, [f0, f1]: [number, number], [v0, v1]: [number, number], easing = EASE.out) =>
  interpolate(frame, [f0, f1], [v0, v1], {easing, extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

/** Keyframe track [[frame, value, easing-into-this-key?], ...], held before the first and after the last key. */
export const keys = (frame: number, track: ([number, number] | [number, number, (t: number) => number])[]) => {
  if (frame <= track[0][0]) return track[0][1];
  for (let i = 1; i < track.length; i++) {
    const [f1, v1, e] = track[i] as [number, number, ((t: number) => number) | undefined];
    const [f0, v0] = track[i - 1];
    if (frame <= f1) return interpolate(frame, [f0, f1], [v0, v1], {easing: e ?? EASE.inOut});
  }
  return track[track.length - 1][1];
};

/** Smooth organic drift in [-amp, amp]. `freq` is cycles per second at 30 fps. */
export const wobble = (frame: number, freq: number, amp: number, seed: number | string = 0) => noise2D(String(seed), (frame / 30) * freq, 0) * amp;

/** A hop of `dur` frames: anticipation squash, airborne arc with stretch, landing squash. y is up-negative. */
export const hop = (frame: number, from: number, dur: number, height: number) => {
  const t = (frame - from) / dur;
  if (t <= 0 || t >= 1) {
    const after = (frame - from - dur) / 6; // settle wobble after landing
    if (t >= 1 && after < 1) return {y: 0, squash: 1 - 0.06 * Math.sin(after * Math.PI) * (1 - after)};
    return {y: 0, squash: 1};
  }
  if (t < 0.15) return {y: 0, squash: 1 - 0.18 * Math.sin((t / 0.15) * (Math.PI / 2))};
  if (t > 0.85) return {y: 0, squash: 1 - 0.2 * Math.sin(((t - 0.85) / 0.15) * Math.PI)};
  const a = (t - 0.15) / 0.7;
  return {y: -height * 4 * a * (1 - a), squash: 1 + 0.14 * Math.cos(a * Math.PI) ** 2 * (a < 0.5 ? 1 : 0.6)};
};

/** Eyelid closure 0..1: a 6-frame blink every 2.5-4.5 s, placed by seed. */
export const blinkAt = (frame: number, seed: number) => {
  let start = Math.floor(20 + ((seed * 37) % 40));
  for (let i = 0; start <= frame; i++) {
    const d = frame - start;
    if (d < 6) return Math.sin((d / 6) * Math.PI) > 0.2 ? Math.min(1, Math.sin((d / 6) * Math.PI) * 1.4) : 0;
    start += 75 + Math.floor(Math.abs(Math.sin((seed + 1) * 12.9898 * (i + 1))) * 60);
  }
  return 0;
};

const db = (x: number) => 10 ** (x / 20);

/** Music gain: `base` dB, ducked `duck` dB while the narrator speaks, with attack before and release after. */
export const duckedVolume = (frame: number, tl: Timeline, {base = -18, duck = -13, attack = 4, release = 12} = {}) => {
  let env = 0;
  for (const l of tl.lines) {
    const up = interpolate(frame, [l.from - attack, l.from], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
    const down = interpolate(frame, [l.to, l.to + release], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
    env = Math.max(env, Math.min(up, down));
  }
  return db(base + duck * env);
};
