// Deterministic particles: drifting leaves, bubbles, sparkles, puffs and bursts. Same frame, same picture.
import {theme} from '../kit/theme';

/** Seeded random in [0, 1). */
export const rand = (seed: number) => {
  const x = Math.sin(seed * 12.9898 + 78.233) * 43758.5453;
  return x - Math.floor(x);
};

const Leaf = ({c}: {c: string}) => (
  <g>
    <path d="M 0 -18 C 14 -10 14 10 0 18 C -14 10 -14 -10 0 -18 Z" fill={c} />
    <path d="M 0 -15 L 0 15" stroke="#00000022" strokeWidth="2" />
  </g>
);

/** Leaves drifting down through a box, looping; `n` leaves, `speed` px per frame. */
export const Leaves = ({frame, x0, x1, y0, y1, n = 8, speed = 2.2, seed = 1, scale = 1, opacity = 1}: {
  frame: number; x0: number; x1: number; y0: number; y1: number; n?: number; speed?: number; seed?: number; scale?: number; opacity?: number;
}) => (
  <g opacity={opacity}>
    {Array.from({length: n}, (_, i) => {
      const r = rand(seed * 100 + i);
      const h = y1 - y0;
      const y = y0 + ((r * h + frame * speed * (0.7 + r * 0.6)) % h);
      const x = x0 + rand(seed * 50 + i) * (x1 - x0) + Math.sin(frame / (18 + r * 14) + i) * 60;
      const col = [theme.orange, '#D9A23C', theme.forest.near, '#C96F3A'][i % 4];
      return (
        <g key={i} transform={`translate(${x} ${y}) rotate(${frame * (2 + r * 3) + i * 40}) scale(${scale * (0.8 + r * 0.6)} ${scale * Math.cos(frame / 9 + i) * 0.9})`}>
          <Leaf c={col} />
        </g>
      );
    })}
  </g>
);

/** Bubbles rising from (x, y) from frame `from`, one every `every` frames. Returns nothing outside [from, to]. */
export const Bubbles = ({frame, x, y, from, to, every = 9, rise = 3, seed = 3}: {frame: number; x: number; y: number; from: number; to: number; every?: number; rise?: number; seed?: number}) => {
  const out = [];
  for (let k = 0; from + k * every <= Math.min(frame, to); k++) {
    const age = frame - (from + k * every);
    if (age > 90) continue;
    const r = 5 + rand(seed + k) * 9;
    out.push(
      <g key={k} transform={`translate(${x + Math.sin(age / 6 + k) * 8} ${y - age * rise})`} opacity={Math.min(1, (90 - age) / 30)}>
        <circle r={r} fill="#fff" fillOpacity="0.25" stroke="#fff" strokeWidth="2.5" />
        <circle cx={-r * 0.35} cy={-r * 0.35} r={r * 0.25} fill="#fff" />
      </g>,
    );
  }
  return <g>{out}</g>;
};

/** A four-point sparkle that pops in and fades over `dur` frames. */
export const Sparkle = ({frame, at, x, y, size = 30, dur = 18, color = '#FFF6D8'}: {frame: number; at: number; x: number; y: number; size?: number; dur?: number; color?: string}) => {
  const t = (frame - at) / dur;
  if (t < 0 || t > 1) return null;
  const s = Math.sin(t * Math.PI) * size;
  return (
    <g transform={`translate(${x} ${y}) rotate(${t * 90})`}>
      <path d={`M 0 ${-s} Q ${s * 0.14} ${-s * 0.14} ${s} 0 Q ${s * 0.14} ${s * 0.14} 0 ${s} Q ${-s * 0.14} ${s * 0.14} ${-s} 0 Q ${-s * 0.14} ${-s * 0.14} 0 ${-s} Z`} fill={color} />
    </g>
  );
};

/** Several sparkles scattered around a point. */
export const SparkleBurst = ({frame, at, x, y, spread = 120, n = 6, size = 34}: {frame: number; at: number; x: number; y: number; spread?: number; n?: number; size?: number}) => (
  <g>
    {Array.from({length: n}, (_, i) => (
      <Sparkle key={i} frame={frame} at={at + i * 2} x={x + (rand(at + i) - 0.5) * spread * 2} y={y + (rand(at + i + 9) - 0.5) * spread * 2} size={size * (0.6 + rand(i) * 0.6)} />
    ))}
  </g>
);

/** A pop: a ring and droplets flying out, `dur` frames from `at`. */
export const PopBurst = ({frame, at, x, y, r = 120, dur = 16, color = '#fff'}: {frame: number; at: number; x: number; y: number; r?: number; dur?: number; color?: string}) => {
  const t = (frame - at) / dur;
  if (t < 0 || t > 1) return null;
  return (
    <g transform={`translate(${x} ${y})`} opacity={1 - t}>
      <circle r={r * (0.6 + t * 0.7)} fill="none" stroke={color} strokeWidth={10 * (1 - t)} />
      {Array.from({length: 10}, (_, i) => {
        const a = (i / 10) * Math.PI * 2 + 0.3;
        const d = r * (0.6 + t * 1.1);
        return <circle key={i} cx={Math.cos(a) * d} cy={Math.sin(a) * d} r={9 * (1 - t)} fill={color} />;
      })}
    </g>
  );
};

/** Things thrown out in arcs (digging): items fly from (x, y) up and over, starting at `from`, one every `every`. */
export const Burst = ({frame, from, to, x, y, every = 3, seed = 7, render}: {
  frame: number; from: number; to: number; x: number; y: number; every?: number; seed?: number; render: (i: number) => React.ReactNode;
}) => {
  const out = [];
  for (let k = 0; from + k * every <= Math.min(frame, to); k++) {
    const age = frame - (from + k * every);
    if (age > 40) continue;
    const vx = (rand(seed + k) - 0.65) * 26;
    const vy = -18 - rand(seed + k + 3) * 14;
    out.push(
      <g key={k} transform={`translate(${x + vx * age} ${y + vy * age + 0.9 * age * age}) rotate(${age * (rand(k) * 30 - 15)})`}>
        {render(k)}
      </g>,
    );
  }
  return <g>{out}</g>;
};

/** Soft dust puffs at (x, y) from `at`. */
export const Puff = ({frame, at, x, y, n = 5, size = 40, dur = 20}: {frame: number; at: number; x: number; y: number; n?: number; size?: number; dur?: number}) => {
  const t = (frame - at) / dur;
  if (t < 0 || t > 1) return null;
  return (
    <g opacity={(1 - t) * 0.8}>
      {Array.from({length: n}, (_, i) => {
        const a = (i / (n - 1)) * Math.PI - Math.PI;
        const d = size * 1.6 * t;
        return <circle key={i} cx={x + Math.cos(a) * d * 1.6} cy={y + Math.sin(a) * d * 0.5} r={size * (0.4 + t * 0.6)} fill="#F6EBDD" />;
      })}
    </g>
  );
};
