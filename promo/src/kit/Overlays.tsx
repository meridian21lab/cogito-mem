// Series overlays, in screen space per cut: the nature-documentary lower third (common name + mock Latin),
// the binocular iris for openings, and Cogi's tail wipe, the series' signature transition.
import type {ReactNode} from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {FORMATS, type FormatId} from './formats';
import {EASE, ease, springAt} from './motion';
import {theme} from './theme';

/** Top-left species card, as in a wildlife documentary. Stays inside the safe zones of both cuts. */
export const LowerThird = ({title, latin, from, to, format}: {title: string; latin: string; from: number; to: number; format: FormatId}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  if (frame < from || frame > to + 12) return null;
  const inn = springAt(frame, from, fps, {damping: 15, stiffness: 170, mass: 0.8});
  const out = ease(frame, [to, to + 12], [0, 1], EASE.in);
  const x = -40 + (1 - inn) * -500 + out * -620;
  const top = format === 'shorts' ? 230 : 60;
  return (
    <div style={{position: 'absolute', left: 70 + x, top, display: 'flex', alignItems: 'stretch', filter: 'drop-shadow(0 10px 18px rgba(43,29,18,0.25))'}}>
      <div style={{width: 14, background: theme.orange, borderRadius: '8px 0 0 8px'}} />
      <div style={{background: theme.paper, padding: '18px 34px 20px 26px', borderRadius: '0 14px 14px 0'}}>
        <div style={{fontFamily: theme.fonts.display, fontWeight: 700, fontSize: 52, color: theme.ink, lineHeight: 1}}>{title}</div>
        <div style={{fontFamily: theme.fonts.body, fontStyle: 'italic', fontSize: 38, color: theme.rust, marginTop: 8, lineHeight: 1.1}}>{latin}</div>
      </div>
    </div>
  );
};

/** A binocular view that opens from `from` to `to`, revealing the full frame. */
export const Binoculars = ({from, to, format}: {from: number; to: number; format: FormatId}) => {
  const frame = useCurrentFrame();
  if (frame > to) return null;
  const {width: W, height: H} = FORMATS[format];
  const t = ease(frame, [from, to], [0, 1], EASE.in);
  const r = 400 + t * 1300;
  const dx = 220 + t * 300;
  return (
    <AbsoluteFill>
      <svg width={W} height={H}>
        <defs>
          <mask id="bino">
            <rect width={W} height={H} fill="#fff" />
            <circle cx={W / 2 - dx} cy={H / 2} r={r} fill="#000" />
            <circle cx={W / 2 + dx} cy={H / 2} r={r} fill="#000" />
          </mask>
        </defs>
        <rect width={W} height={H} fill={theme.ink} mask="url(#bino)" />
      </svg>
    </AbsoluteFill>
  );
};

const TAIL = 'M100 170 C50 174 16 134 24 88 C30 50 62 20 100 22 C130 24 144 52 128 68 C117 78 99 71 101 57 C102 50 109 47 114 51 C108 44 98 46 96 56 C94 70 104 84 112 98 L114 160 Z';

/**
 * Cogi's giant tail sweeps right to left over `dur` frames from `from`; `after` is shown behind the
 * tail's trailing edge, so the tail wipes from one scene to the next.
 */
export const TailWipe = ({from, dur, format, after}: {from: number; dur: number; format: FormatId; after: ReactNode}) => {
  const frame = useCurrentFrame();
  const {width: W, height: H} = FORMATS[format];
  const t = ease(frame, [from, from + dur], [0, 1], EASE.inOut);
  if (frame < from) return null;
  const s = H / 120;
  const tx = W + 200 - t * (W + 200 + 150 * s);
  const edge = Math.max(0, tx + 40 * s);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{clipPath: `inset(0 0 0 ${edge}px)`}}>{after}</AbsoluteFill>
      {t < 1 ? (
        <svg width={W} height={H} style={{position: 'absolute', inset: 0}}>
          <g transform={`translate(${tx} ${H * 0.55}) scale(${s}) rotate(${-20 + t * 25}) translate(-70 -100)`}>
            <path d={TAIL} fill={theme.cogi.dark} />
            <path d="M96 158 C60 160 36 128 42 92 C47 62 70 38 98 37 C112 37 122 45 121 55 C112 43 92 43 82 56 C70 74 72 112 100 140 Z" fill={theme.cogi.light} />
          </g>
        </svg>
      ) : null}
    </AbsoluteFill>
  );
};
