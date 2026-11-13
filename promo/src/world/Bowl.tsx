// Goldie's bowl, which stands for the context window: what the assistant can still see. `x`, `y` is the
// bottom centre on the desk. Children (Goldie, bubbles) are drawn in the bowl's own space, clipped to the
// water, with the bowl's centre at (0, -CY).
import type {ReactNode} from 'react';
import {theme} from '../kit/theme';

export const BOWL = {R: 210, CY: 205, rimDy: 175};

const W = theme.water;

export const Bowl = ({x, y, frame, slosh = 0, level = 0, swirl = 0, children}: {
  x: number;
  y: number;
  frame: number;
  /** 0..1 wave height (the chat ending sloshes it). */
  slosh?: number;
  /** Water drop in px (positive lowers the surface). */
  level?: number;
  /** 0..1 a whirlpool swirl in the water. */
  swirl?: number;
  children?: ReactNode;
}) => {
  const {R, CY, rimDy} = BOWL;
  const rimY = -CY - rimDy;
  const rimX = Math.sqrt(R * R - rimDy * rimDy);
  const surf = rimY + 48 + level;
  const amp = 4 + slosh * 26;
  const wave = Array.from({length: 25}, (_, i) => {
    const px = -R + (i / 24) * 2 * R;
    const py = surf + Math.sin(i / 2.2 + frame / 7) * amp * 0.5 + Math.sin(i / 5 - frame / 11) * amp * 0.5 + (px / R) * slosh * 22 * Math.sin(frame / 6);
    return `${px.toFixed(1)} ${py.toFixed(1)}`;
  });
  const id = `bowl-${Math.round(x)}`;
  return (
    <g transform={`translate(${x} ${y})`}>
      <defs>
        <clipPath id={`${id}-in`}>
          <circle cx="0" cy={-CY} r={R - 6} />
        </clipPath>
        <linearGradient id={`${id}-water`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={W.top} stopOpacity="0.92" />
          <stop offset="1" stopColor={W.deep} stopOpacity="0.95" />
        </linearGradient>
        <radialGradient id={`${id}-glass`} cx="0.35" cy="0.3" r="0.8">
          <stop offset="0" stopColor="#ffffff" stopOpacity="0.22" />
          <stop offset="1" stopColor="#ffffff" stopOpacity="0.04" />
        </radialGradient>
      </defs>
      {/* contact shadow on the desk */}
      <ellipse cx="10" cy="4" rx="170" ry="16" fill={theme.ink} opacity="0.14" />
      <circle cx="0" cy={-CY} r={R} fill={`url(#${id}-glass)`} />
      <g clipPath={`url(#${id}-in)`}>
        <path d={`M ${wave.join(' L ')} L ${R} 40 L ${-R} 40 Z`} fill={`url(#${id}-water)`} />
        <path d={`M ${wave.join(' L ')}`} fill="none" stroke="#fff" strokeOpacity="0.55" strokeWidth="5" />
        {swirl > 0.01 ? (
          <g transform={`translate(0 ${-CY + 30}) rotate(${frame * 14})`} opacity={swirl * 0.6}>
            {[0, 1, 2].map((i) => (
              <path key={i} d={`M ${30 + i * 40} 0 A ${30 + i * 40} ${18 + i * 14} 0 1 1 ${-(30 + i * 40)} 0`} fill="none" stroke="#fff" strokeWidth="6" strokeLinecap="round" transform={`rotate(${i * 120})`} />
            ))}
          </g>
        ) : null}
        {/* seaweed */}
        {[-120, -92, 118].map((sx, i) => (
          <path
            key={sx}
            d={`M ${sx} -16 C ${sx + 18 + Math.sin(frame / 18 + i) * 14} -70 ${sx - 20 + Math.sin(frame / 15 + i) * 16} -110 ${sx + Math.sin(frame / 20 + i) * 22} ${-150 - i * 18}`}
            fill="none"
            stroke={theme.forest.near}
            strokeWidth="11"
            strokeLinecap="round"
          />
        ))}
        {/* gravel */}
        {Array.from({length: 34}, (_, i) => {
          const gx = -150 + ((i * 53) % 300);
          const gy = -16 - ((i * 29) % 26);
          const col = [theme.sand, '#E7C9A2', '#D9A27A', '#BFD3B8'][i % 4];
          return <ellipse key={i} cx={gx} cy={gy} rx={13 + (i % 3) * 3} ry={9} fill={col} />;
        })}
        {children}
      </g>
      {/* glass: outline from rim round the bottom, the rim, and highlights */}
      <path d={`M ${-rimX} ${rimY} A ${R} ${R} 0 1 0 ${rimX} ${rimY}`} fill="none" stroke="#8FC6C8" strokeOpacity="0.9" strokeWidth="7" />
      <ellipse cx="0" cy={rimY} rx={rimX} ry="17" fill="none" stroke="#8FC6C8" strokeOpacity="0.9" strokeWidth="7" />
      <path d={`M ${-R * 0.72} ${-CY - R * 0.42} A ${R * 0.85} ${R * 0.85} 0 0 0 ${-R * 0.62} ${-CY + R * 0.55}`} fill="none" stroke="#fff" strokeOpacity="0.7" strokeWidth="12" strokeLinecap="round" />
      <path d={`M ${R * 0.55} ${-CY - R * 0.55} A ${R * 0.8} ${R * 0.8} 0 0 1 ${R * 0.72} ${-CY - R * 0.25}`} fill="none" stroke="#fff" strokeOpacity="0.55" strokeWidth="8" strokeLinecap="round" />
    </g>
  );
};

/** A message held in the bowl: a rounded bubble with text, wobbling in the water. */
export const MessageBubble = ({x, y, text, scale = 1, frame, opacity = 1}: {x: number; y: number; text: string[]; scale?: number; frame: number; opacity?: number}) => {
  const w = 300;
  const h = 36 + text.length * 38;
  const r = Math.sin(frame / 14) * 3;
  return (
    <g transform={`translate(${x} ${y + Math.sin(frame / 10) * 5}) rotate(${r}) scale(${scale})`} opacity={opacity}>
      <rect x={-w / 2} y={-h / 2} width={w} height={h} rx={h / 2.4} fill="#fff" fillOpacity="0.88" stroke="#fff" strokeWidth="4" />
      <circle cx={-w / 2 + 26} cy={-h / 2 + 16} r="7" fill="#fff" />
      {text.map((t, i) => (
        <text key={i} x="0" y={-h / 2 + 46 + i * 38} textAnchor="middle" fontFamily={theme.fonts.display} fontWeight={700} fontSize="31" fill={theme.ink}>
          {t}
        </text>
      ))}
    </g>
  );
};
