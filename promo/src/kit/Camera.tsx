// The camera: one world, framed per cut. A shot is the world point at the frame's centre plus a zoom, so
// the 4:5 feed cut automatically shows the central band of what the 9:16 cut shows. Layers with depth < 1
// drift less (parallax); fast moves get a directional blur from the camera's own speed (a whip pan).
import {createContext, useContext, type ReactNode} from 'react';
import {EASE, wobble} from './motion';
import {FORMATS, type FormatId} from './formats';
import {interpolate} from 'remotion';

export type Shot = {x: number; y: number; zoom: number; rot?: number};

/** Parallax reference: background layers are drawn as if seen from here. */
export const REF = {x: 1000, y: 1000};

type Key = [number, Shot] | [number, Shot, (t: number) => number];

/** Shot at `frame` from keyframes [[frame, shot, easing-into-it?], ...]. */
export const shotTrack = (frame: number, keys: Key[]): Shot => {
  if (frame <= keys[0][0]) return keys[0][1];
  for (let i = 1; i < keys.length; i++) {
    const [f1, s1, e] = keys[i] as [number, Shot, ((t: number) => number) | undefined];
    const [f0, s0] = keys[i - 1];
    if (frame <= f1) {
      const t = interpolate(frame, [f0, f1], [0, 1], {easing: e ?? EASE.inOut});
      const lerp = (a: number, b: number) => a + (b - a) * t;
      // zoom interpolates in log space so a push-in feels even
      return {x: lerp(s0.x, s1.x), y: lerp(s0.y, s1.y), zoom: Math.exp(lerp(Math.log(s0.zoom), Math.log(s1.zoom))), rot: lerp(s0.rot ?? 0, s1.rot ?? 0)};
    }
  }
  return keys[keys.length - 1][1];
};

/** Hand-held drift plus decaying shakes at the given frames. */
export const handheld = (frame: number, shot: Shot, shakes: [number, number][] = [], amp = 5): Shot => {
  let sx = 0;
  let sy = 0;
  for (const [at, power] of shakes) {
    const d = frame - at;
    if (d >= 0 && d < 14) {
      const k = power * (1 - d / 14) ** 2;
      sx += Math.sin(d * 2.7) * k;
      sy += Math.cos(d * 3.3) * k;
    }
  }
  return {
    ...shot,
    x: shot.x + (wobble(frame, 0.25, amp, 'hx') + sx) / shot.zoom,
    y: shot.y + (wobble(frame, 0.22, amp, 'hy') + sy) / shot.zoom,
    rot: (shot.rot ?? 0) + wobble(frame, 0.18, 0.35, 'hr'),
  };
};

const Ctx = createContext<{shot: Shot; W: number; H: number}>({shot: {x: 0, y: 0, zoom: 1}, W: 1080, H: 1920});

export const Camera = ({shot, prev, format, children}: {shot: Shot; prev: Shot; format: FormatId; children: ReactNode}) => {
  const {width: W, height: H} = FORMATS[format];
  // blur from sideways travel only; a zoom alone stays sharp, and a jump of more than 300 px is a cut
  const dx = Math.abs(shot.x - prev.x) * shot.zoom;
  const dy = Math.abs(shot.y - prev.y) * shot.zoom;
  const cut = Math.hypot(dx, dy) > 300;
  const bx = cut ? 0 : Math.min(36, Math.max(0, dx - 12) * 0.3);
  const by = cut ? 0 : Math.min(36, Math.max(0, dy - 12) * 0.3);
  const blur = bx + by > 1.2;
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{position: 'absolute', inset: 0}}>
      <defs>
        <filter id="whip" x="-5%" y="-5%" width="110%" height="110%" colorInterpolationFilters="sRGB">
          <feGaussianBlur stdDeviation={`${bx.toFixed(1)} ${by.toFixed(1)}`} />
        </filter>
      </defs>
      <g filter={blur ? 'url(#whip)' : undefined}>
        <Ctx.Provider value={{shot, W, H}}>{children}</Ctx.Provider>
      </g>
    </svg>
  );
};

export const Layer = ({depth = 1, children}: {depth?: number; children: ReactNode}) => {
  const {shot, W, H} = useContext(Ctx);
  const cx = REF.x + (shot.x - REF.x) * depth;
  const cy = REF.y + (shot.y - REF.y) * depth;
  const z = shot.zoom ** depth;
  return <g transform={`translate(${W / 2} ${H / 2}) rotate(${shot.rot ?? 0}) scale(${z}) translate(${-cx} ${-cy})`}>{children}</g>;
};
