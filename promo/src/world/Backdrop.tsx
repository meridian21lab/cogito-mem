// The forest edge behind the desk, in parallax layers. Each layer is drawn in world units around the
// parallax reference point (see Camera's REF), so deeper layers drift less as the camera moves.
import {theme} from '../kit/theme';

const F = theme.forest;

export const Sky = () => (
  <g>
    <defs>
      <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor={theme.sky.top} />
        <stop offset="1" stopColor={theme.sky.bottom} />
      </linearGradient>
      <radialGradient id="sun" cx="0.5" cy="0.5" r="0.5">
        <stop offset="0" stopColor="#FFF4D6" stopOpacity="1" />
        <stop offset="0.35" stopColor={theme.sky.sun} stopOpacity="0.8" />
        <stop offset="1" stopColor={theme.sky.sun} stopOpacity="0" />
      </radialGradient>
    </defs>
    <rect x="-3000" y="-3000" width="8000" height="8000" fill="url(#sky)" />
    <circle cx="180" cy="260" r="900" fill="url(#sun)" />
  </g>
);

const crowns = (n: number, x0: number, dx: number, y: number, r: number, seed: number) =>
  Array.from({length: n}, (_, i) => {
    const j = Math.sin((i + 1) * 12.9898 * seed) * 43758.5453;
    const f = j - Math.floor(j);
    return {cx: x0 + i * dx + f * dx * 0.4, cy: y - f * r * 0.9, r: r * (0.75 + f * 0.5)};
  });

export const FarTrees = () => (
  <g>
    {crowns(26, -1400, 180, 1150, 150, 1.3).map((c, i) => (
      <circle key={i} cx={c.cx} cy={c.cy} r={c.r} fill={F.far} />
    ))}
    <rect x="-3000" y="1150" width="8000" height="3000" fill={F.far} />
    <rect x="-3000" y="900" width="8000" height="600" fill={theme.sky.bottom} opacity="0.35" />
  </g>
);

export const MidTrees = ({frame}: {frame: number}) => (
  <g>
    {crowns(16, -1200, 300, 1050, 210, 2.7).map((c, i) => (
      <g key={i}>
        <rect x={c.cx - 22} y={c.cy} width="44" height="900" fill={F.trunk} opacity="0.55" />
        <circle cx={c.cx + Math.sin(frame / 40 + i) * 4} cy={c.cy} r={c.r} fill={F.mid} />
        <circle cx={c.cx - c.r * 0.35} cy={c.cy - c.r * 0.3} r={c.r * 0.55} fill="#B4C796" opacity="0.6" />
      </g>
    ))}
    <rect x="-3000" y="1380" width="8000" height="3000" fill={F.mid} />
  </g>
);

export const Ground = ({y, frame = 0}: {y: number; frame?: number}) => (
  <g>
    <defs>
      <linearGradient id="ground" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor={F.near} />
        <stop offset="0.25" stopColor={F.deep} />
        <stop offset="1" stopColor="#465E3E" />
      </linearGradient>
    </defs>
    {crowns(22, -1000, 200, y - 30, 110, 4.1).map((c, i) => (
      <circle key={i} cx={c.cx} cy={c.cy + 60} r={c.r} fill={F.near} />
    ))}
    <rect x="-3000" y={y} width="8000" height="3000" fill="url(#ground)" />
    {/* grass tufts along the edge, swaying a little */}
    {Array.from({length: 70}, (_, i) => {
      const gx = -600 + i * 48 + ((i * 37) % 23);
      const h = 26 + ((i * 53) % 30);
      const sway = Math.sin(frame / 25 + i) * 4;
      return (
        <path
          key={i}
          d={`M ${gx - 10} ${y + 6} Q ${gx - 6 + sway} ${y - h * 0.6} ${gx - 2 + sway * 1.5} ${y - h} Q ${gx} ${y - h * 0.4} ${gx + 2} ${y + 6} Q ${gx + 6 + sway} ${y - h * 0.7} ${gx + 14 + sway * 1.5} ${y - h * 0.8} Q ${gx + 8} ${y - h * 0.3} ${gx + 10} ${y + 6} Z`}
          fill={i % 3 ? F.near : '#93AE7A'}
        />
      );
    })}
    {/* darker patches and a few pebbles and mushrooms */}
    {Array.from({length: 18}, (_, i) => (
      <ellipse key={i} cx={-500 + ((i * 211) % 3000)} cy={y + 60 + ((i * 97) % 300)} rx={60 + (i % 4) * 30} ry={14 + (i % 3) * 6} fill="#3F5638" opacity="0.35" />
    ))}
    {[[1420, 0], [1905, 1], [1960, 2]].map(([mx, i]) => (
      <g key={i} transform={`translate(${mx} ${y + 14}) scale(${1 - i * 0.2})`}>
        <rect x="-6" y="-26" width="12" height="28" rx="5" fill={theme.cream} />
        <path d="M -26 -22 Q 0 -54 26 -22 Z" fill={theme.rust} />
        <circle cx="-8" cy="-32" r="4" fill={theme.cream} />
        <circle cx="8" cy="-36" r="3" fill={theme.cream} />
      </g>
    ))}
  </g>
);
