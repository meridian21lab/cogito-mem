// Cogi's tree at the desk's edge. The hollow (its floor level with the desk top) is the pantry: shelves of
// acorns, each a kept message with its date. (x, y) is the hollow's floor at the trunk's centre line.
import {theme} from '../kit/theme';

const F = theme.forest;
const A = theme.acorn;

export const HOLLOW = {w: 300, h: 420, shelves: [-150, -290], perShelf: 5, gap: 50};

/** World position of the nth acorn slot on the shelves (relative to the tree's anchor). */
export const shelfSlot = (n: number) => {
  const shelf = Math.floor(n / HOLLOW.perShelf) % HOLLOW.shelves.length;
  const i = n % HOLLOW.perShelf;
  return {x: -100 + i * HOLLOW.gap, y: HOLLOW.shelves[shelf] - 4};
};

export const SmallAcorn = ({x, y, s = 1, rot = 0, tag, tagOpacity = 1, tagLow = false}: {x: number; y: number; s?: number; rot?: number; tag?: string; tagOpacity?: number; tagLow?: boolean}) => (
  <g transform={`translate(${x} ${y}) rotate(${rot}) scale(${s})`}>
    <ellipse cx="0" cy="-17" rx="14" ry="17" fill={A.nut} />
    <ellipse cx="-5" cy="-21" rx="4" ry="7" fill={A.light} opacity="0.7" />
    <path d="M -17 -26 Q 0 -50 17 -26 Z" fill={A.cap} />
    <rect x="-2" y="-52" width="4" height="9" rx="2" fill={A.cap} />
    {tag ? (
      <g opacity={tagOpacity}>
        <path d={tagLow ? 'M 8 -18 L 20 -14' : 'M 6 -30 L 22 -40'} stroke={theme.cream} strokeWidth="1.6" />
        <g transform={tagLow ? 'translate(18 -20) rotate(6)' : 'translate(20 -52) rotate(-8)'}>
          <rect x="0" y="0" width="58" height="22" rx="4" fill={theme.cream} />
          <text x="29" y="16" textAnchor="middle" fontFamily={theme.fonts.display} fontWeight={700} fontSize="14" fill={theme.rust}>
            {tag}
          </text>
        </g>
      </g>
    ) : null}
  </g>
);

export const Tree = ({x, y, ground, frame, shelf = 0, tags = 0, labels = [], sign = 0, inside = 1}: {
  x: number;
  y: number;
  ground: number;
  frame: number;
  /** Acorns on the shelves. */
  shelf?: number;
  /** How many of them have their date tag (fractional = the last one stamping in). */
  tags?: number;
  /** Date tag per shelf slot. */
  labels?: string[];
  /** The "your computer" sign, 0 hidden .. 1 hung. */
  sign?: number;
  /** Warmth of the light inside the hollow. */
  inside?: number;
}) => {
  const {w, h} = HOLLOW;
  const arch = `M ${-w / 2} 0 L ${-w / 2} ${-h + w / 2} A ${w / 2} ${w / 2} 0 0 1 ${w / 2} ${-h + w / 2} L ${w / 2} 0 Z`;
  const g = ground - y;
  const swing = Math.sin(frame / 9) * 6 * (1 - Math.min(1, sign)) + Math.sin(frame / 23) * 2;
  return (
    <g transform={`translate(${x} ${y})`}>
      <defs>
        <radialGradient id="hollow-glow" cx="0.5" cy="0.62" r="0.62">
          <stop offset="0" stopColor="#8A5A30" stopOpacity={0.9 * inside} />
          <stop offset="1" stopColor="#2B1A0E" />
        </radialGradient>
        <linearGradient id="trunk-shade" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#9A6B43" />
          <stop offset="0.35" stopColor={F.trunk} />
          <stop offset="1" stopColor={F.trunkDark} />
        </linearGradient>
      </defs>
      {/* trunk with roots */}
      <path
        d={`M -190 -2600 L 190 -2600 C 200 -1200 190 ${g - 260} 230 ${g - 60} C 270 ${g - 10} 330 ${g} 360 ${g + 10} L -360 ${g + 10} C -330 ${g} -270 ${g - 10} -230 ${g - 60} C -190 ${g - 260} -200 -1200 -190 -2600 Z`}
        fill="url(#trunk-shade)"
      />
      {Array.from({length: 9}, (_, i) => {
        const bx = -150 + i * 38;
        return (
          <path
            key={i}
            d={`M ${bx} -2500 C ${bx + 14} -1900 ${bx - 16} -1300 ${bx + 8} -700 S ${bx - 10} ${g - 300} ${bx + (bx > 0 ? 30 : -30)} ${g - 40}`}
            fill="none"
            stroke={F.trunkDark}
            strokeWidth={i % 3 === 0 ? 7 : 4}
            opacity={0.28}
          />
        );
      })}
      {/* branch over the desk */}
      <g>
        <path d="M -170 -560 C -320 -600 -460 -640 -640 -610 C -560 -660 -420 -690 -300 -670 C -250 -660 -200 -650 -170 -640 Z" fill={F.trunk} />
        {[
          [-640, -640, 90],
          [-540, -700, 70],
          [-470, -620, 60],
          [-700, -580, 55],
        ].map(([cx, cy, r], i) => (
          <circle key={i} cx={cx} cy={cy + Math.sin(frame / 30 + i) * 3} r={r} fill={i % 2 ? F.near : F.mid} />
        ))}
      </g>
      {/* hollow: rim, warm inside, shelves of kept acorns */}
      <path d={arch} transform="scale(1.12 1.06)" fill="#5C3B21" />
      <path d={arch} fill="url(#hollow-glow)" />
      {HOLLOW.shelves.map((sy) => (
        <g key={sy}>
          <rect x={-w / 2 + 14} y={sy} width={w - 28} height="14" rx="4" fill={theme.wood.top} />
          <rect x={-w / 2 + 14} y={sy + 14} width={w - 28} height="6" fill={theme.wood.dark} opacity="0.6" />
        </g>
      ))}
      {Array.from({length: Math.floor(shelf)}, (_, n) => {
        const s = shelfSlot(n);
        const t = Math.max(0, Math.min(1, tags - n));
        return <SmallAcorn key={n} x={s.x} y={s.y} s={0.95} rot={(n * 37) % 9 - 4} tag={t > 0 ? labels[n] ?? '13 NOV' : undefined} tagOpacity={t} tagLow={n % 2 === 1} />;
      })}
      {/* lip of the hollow, level with the desk */}
      <path d={`M ${-w / 2 - 22} 2 Q 0 26 ${w / 2 + 22} 2`} fill="none" stroke="#9B6B45" strokeWidth="16" strokeLinecap="round" />
      {/* the sign */}
      {sign > 0.001 ? (
        <g transform={`translate(0 ${-560 - (1 - Math.min(1, sign)) * 260}) rotate(${swing})`} opacity={Math.min(1, sign * 3)}>
          <path d="M -70 0 L 0 -40 L 70 0" fill="none" stroke="#5C3B21" strokeWidth="4" />
          <circle cx="0" cy="-40" r="6" fill="#C9B49A" />
          <rect x="-150" y="0" width="300" height="78" rx="10" fill="#C98B55" stroke="#9C6234" strokeWidth="6" />
          <text x="0" y="51" textAnchor="middle" fontFamily={theme.fonts.display} fontWeight={700} fontSize="34" fill={theme.ink}>
            your computer
          </text>
        </g>
      ) : null}
    </g>
  );
};
