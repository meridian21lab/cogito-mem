// Props for the series: flapping wings, winged chats and acorns, the cloud's placards and magnifier, a leaf
// umbrella and a small rain shower. Pure functions of the frame; (x, y) places each one in the world.
import {theme} from '../kit/theme';
import {rand} from './Particles';
import {SmallAcorn} from './Tree';

const WING = 'M 0 0 C -8 -34 -56 -56 -88 -40 C -70 -32 -66 -20 -58 -12 C -76 -12 -84 -2 -86 6 C -54 12 -22 8 0 0 Z';

/** A pair of wings attached at (0, 0); `flap` -1..1 beats them. */
export const Wings = ({flap, s = 1, spread = 18}: {flap: number; s?: number; spread?: number}) => {
  const a = -8 + flap * 30;
  const sy = 0.75 + flap * 0.25;
  return (
    <g transform={`scale(${s})`}>
      {[-1, 1].map((side) => (
        <g key={side} transform={`translate(${side * spread} 0) scale(${-side} 1) rotate(${a}) scale(1 ${sy})`}>
          <path d={WING} fill={theme.paper} stroke={theme.ink} strokeWidth="5" strokeLinejoin="round" />
          <path d="M -20 -10 C -38 -18 -54 -24 -70 -30 M -26 -2 C -44 -4 -60 -4 -76 -2" fill="none" stroke={theme.ink} strokeWidth="3" strokeLinecap="round" opacity="0.35" />
        </g>
      ))}
    </g>
  );
};

/** A chat bubble with wings, flapping. `phase` offsets its wingbeat. */
export const WingedBubble = ({x, y, frame, s = 1, rot = 0, phase = 0, opacity = 1}: {x: number; y: number; frame: number; s?: number; rot?: number; phase?: number; opacity?: number}) => {
  const flap = Math.sin(frame * 0.55 + phase);
  const bob = Math.sin(frame * 0.55 + phase - 1.2) * 6;
  return (
    <g transform={`translate(${x} ${y + bob}) rotate(${rot}) scale(${s})`} opacity={opacity}>
      <g transform="translate(0 -30)">
        <Wings flap={flap} spread={22} />
      </g>
      <path d="M -40 34 L -52 62 L -14 38 Z" fill={theme.paper} stroke={theme.ink} strokeWidth="5" strokeLinejoin="round" />
      <rect x="-66" y="-40" width="132" height="80" rx="34" fill={theme.paper} stroke={theme.ink} strokeWidth="5" />
      <path d="M -44 37 L -14 37" stroke={theme.paper} strokeWidth="7" />
      {[-26, 0, 26].map((dx, i) => (
        <circle key={dx} cx={dx} cy={2 + Math.sin(frame * 0.3 + phase + i) * 2} r="8" fill={theme.ink} />
      ))}
    </g>
  );
};

/** An acorn that has grown wings and is trying to leave. */
export const WingedAcorn = ({x, y, frame, s = 1, rot = 0, phase = 0, wings = 1}: {x: number; y: number; frame: number; s?: number; rot?: number; phase?: number; wings?: number}) => {
  const flap = Math.sin(frame * 0.9 + phase);
  return (
    <g transform={`translate(${x} ${y}) rotate(${rot}) scale(${s})`}>
      {wings > 0.01 ? (
        <g transform={`translate(0 -30) scale(${wings * 0.42})`}>
          <Wings flap={flap} spread={14} />
        </g>
      ) : null}
      <SmallAcorn x={0} y={0} />
    </g>
  );
};

const KeyIcon = () => (
  <g fill="none" stroke={theme.rust} strokeWidth="9" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="-16" cy="0" r="15" />
    <path d="M -1 0 L 34 0 M 22 0 L 22 13 M 33 0 L 33 10" />
  </g>
);

/**
 * The cloud's placard, held at the bottom of its handle (x, y). `kind` picks the ask; the board is about
 * 250 x 120 at scale 1, above a short handle.
 */
export const Placard = ({x, y, kind, s = 1, rot = 0, opacity = 1}: {x: number; y: number; kind: 'signup' | 'key'; s?: number; rot?: number; opacity?: number}) => (
  <g transform={`translate(${x} ${y}) rotate(${rot}) scale(${s})`} opacity={opacity}>
    <rect x="-9" y="-120" width="18" height="120" rx="6" fill={theme.wood.edge} />
    <g transform="translate(0 -180)">
      <rect x="-128" y="-62" width="256" height="124" rx="18" fill={theme.paper} stroke={theme.ink} strokeWidth="7" />
      {kind === 'signup' ? (
        <text x="0" y="17" textAnchor="middle" fontFamily={theme.fonts.display} fontWeight={700} fontSize="52" fill={theme.ink}>
          Sign up!
        </text>
      ) : (
        <>
          <g transform="translate(-90 0) scale(0.9)">
            <KeyIcon />
          </g>
          <text x="38" y="16" textAnchor="middle" fontFamily={theme.fonts.display} fontWeight={700} fontSize="42" fill={theme.ink}>
            API key?
          </text>
        </>
      )}
    </g>
  </g>
);

/** A magnifying glass, held at the end of its handle (x, y); the lens is about 150 across at scale 1. */
export const Magnifier = ({x, y, s = 1, rot = 0, opacity = 1}: {x: number; y: number; s?: number; rot?: number; opacity?: number}) => (
  <g transform={`translate(${x} ${y}) rotate(${rot}) scale(${s})`} opacity={opacity}>
    <rect x="-13" y="-110" width="26" height="110" rx="11" fill={theme.wood.edge} />
    <rect x="-16" y="-128" width="32" height="26" rx="6" fill="#6E7884" />
    <circle cx="0" cy="-200" r="72" fill="#DDF1FA" fillOpacity="0.35" stroke={theme.ink} strokeWidth="13" />
    <path d="M -40 -232 Q -22 -252 4 -252" fill="none" stroke="#fff" strokeWidth="9" strokeLinecap="round" opacity="0.85" />
  </g>
);

/** A big leaf held as an umbrella, its stem's bottom at (x, y); `open` 0..1 swings it up. */
export const LeafUmbrella = ({x, y, open, s = 1, tilt = 0}: {x: number; y: number; open: number; s?: number; tilt?: number}) => {
  if (open <= 0.01) return null;
  const F = theme.forest;
  return (
    <g transform={`translate(${x} ${y}) rotate(${tilt - (1 - open) * 70}) scale(${s * (0.4 + open * 0.6)})`}>
      <path d="M 0 0 L 0 -170" stroke="#4C6B3E" strokeWidth="10" strokeLinecap="round" />
      <g transform="translate(0 -170)">
        <path d="M -190 18 C -170 -110 170 -110 190 18 C 140 -6 70 -2 0 8 C -70 -2 -140 -6 -190 18 Z" fill={F.near} />
        <path d="M -150 -2 C -110 -70 90 -84 130 -28 C 70 -40 -40 -40 -150 -2 Z" fill="#9DB884" opacity="0.6" />
        <path d="M 0 8 C 4 -30 2 -60 0 -78" stroke="#4C6B3E" strokeWidth="6" fill="none" strokeLinecap="round" />
        {[-1, 1].map((side) =>
          [0.3, 0.6].map((k) => <path key={`${side}${k}`} d={`M ${side * 2} ${-60 * (1 - k)} Q ${side * 70 * k} ${-50 * (1 - k) - 20} ${side * 150 * k} ${-6 * k}`} stroke="#4C6B3E" strokeWidth="4" fill="none" opacity="0.6" />),
        )}
      </g>
    </g>
  );
};

/**
 * Rain from a cloud's underside: drops fall from y0 to y1 across [x0, x1], from frame `from` to `to`, and
 * splash where they land. `fade` frames of fade in and out.
 */
export const Rain = ({frame, from, to, x0, x1, y0, y1, n = 26, speed = 26, seed = 11, fade = 8}: {
  frame: number; from: number; to: number; x0: number; x1: number; y0: number; y1: number; n?: number; speed?: number; seed?: number; fade?: number;
}) => {
  if (frame < from || frame > to + 20) return null;
  const h = y1 - y0;
  const period = h / speed;
  const out = [];
  for (let i = 0; i < n; i++) {
    const offset = rand(seed + i) * period;
    const age = frame - from - offset;
    if (age < 0) continue;
    const cycle = Math.floor(age / period);
    const start = from + offset + cycle * period;
    if (start > to) continue;
    const t = (age % period) / period;
    const x = x0 + rand(seed + i * 7 + cycle * 13) * (x1 - x0);
    const y = y0 + t * h;
    out.push(<path key={`d${i}`} d={`M ${x} ${y - 34} L ${x - 4} ${y}`} stroke="#86A9CC" strokeWidth="7" strokeLinecap="round" opacity="0.85" />);
    if (t > 0.82) {
      const k = (t - 0.82) / 0.18;
      out.push(
        <g key={`s${i}`} opacity={1 - k}>
          <circle cx={x - 12 - k * 16} cy={y1 - 6 - k * 18} r="4" fill="#86A9CC" />
          <circle cx={x + 10 + k * 16} cy={y1 - 6 - k * 16} r="4" fill="#86A9CC" />
        </g>,
      );
    }
  }
  const o = Math.min(1, (frame - from) / fade, Math.max(0, (to + 20 - frame) / 20));
  return <g opacity={o}>{out}</g>;
};

/** A comic impact star at (x, y): pops in big and shrinks away over `dur` frames from `at`. */
export const ImpactStar = ({frame, at, x, y, r = 80, dur = 10, rot = 0}: {frame: number; at: number; x: number; y: number; r?: number; dur?: number; rot?: number}) => {
  const t = (frame - at) / dur;
  if (t < 0 || t > 1) return null;
  const k = t < 0.25 ? t / 0.25 : 1 - (t - 0.25) / 0.75;
  const pts = Array.from({length: 18}, (_, i) => {
    const a = (i / 18) * Math.PI * 2;
    const rr = (i % 2 ? 0.48 : 1) * r * (0.9 + 0.12 * Math.sin(i * 3.7));
    return `${(Math.cos(a) * rr).toFixed(1)},${(Math.sin(a) * rr).toFixed(1)}`;
  }).join(' ');
  return (
    <g transform={`translate(${x} ${y}) rotate(${rot + t * 20}) scale(${0.4 + k * 0.8})`} opacity={Math.min(1, k * 2)}>
      <polygon points={pts} fill={theme.orange} stroke={theme.ink} strokeWidth="7" strokeLinejoin="round" />
      <polygon points={pts} fill="#FFE08A" transform="scale(0.55)" />
    </g>
  );
};
