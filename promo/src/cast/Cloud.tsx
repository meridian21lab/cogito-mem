// The cloud: "someone else's cloud", a big, friendly, slightly too eager salesman. It gulps chats, wants an
// account and a key, reads everything through a magnifier, and turns grey and rains when refused.
// (x, y) is its centre; it is about 570 wide and 330 tall at scale 1. A pure function of the pose.
import {theme} from '../kit/theme';

export type CloudMouth = 'smile' | 'grin' | 'open' | 'frown' | 'o';

export type CloudPose = {
  x: number;
  y: number;
  scale: number;
  /** Degrees. */
  tilt: number;
  /** 1 neutral; below 1 squashes (wider), above 1 stretches. */
  squash: number;
  /** Pupils' offset, -1..1 each way. */
  look: [number, number];
  blink: number;
  mouth: CloudMouth;
  /** How wide an 'open' mouth is, 0..1 (gulping). */
  open: number;
  /** Brows raised 1 .. lowered -1. */
  brow: number;
  /** Inner brow ends pulled down, 0..1 (grumpy). */
  grump: number;
  /** Reading glasses, 0 off (above the frame of the face) .. 1 on. */
  glasses: number;
  /** 0 white .. 1 sulking grey. */
  grey: number;
  /** Puffed cheeks before a huff, 0..1. */
  puff: number;
};

export const CLOUD_REST: CloudPose = {
  x: 0, y: 0, scale: 1, tilt: 0, squash: 1, look: [0, 0], blink: 0, mouth: 'grin', open: 0, brow: 0, grump: 0, glasses: 0, grey: 0, puff: 0,
};

const PUFFS: [number, number, number][] = [
  [-175, -5, 105],
  [-65, -80, 140],
  [85, -88, 132],
  [200, -8, 96],
];
const BASE = {x: -280, y: -30, w: 560, h: 140, r: 70};

const hex = (c: string) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
/** Mix two #rrggbb colours. */
export const mix = (a: string, b: string, t: number) => {
  const A = hex(a);
  const B = hex(b);
  return `#${A.map((v, i) => Math.round(v + (B[i] - v) * t).toString(16).padStart(2, '0')).join('')}`;
};

const Shapes = (props: React.SVGProps<SVGGElement>) => (
  <g {...props}>
    <rect x={BASE.x} y={BASE.y} width={BASE.w} height={BASE.h} rx={BASE.r} />
    {PUFFS.map(([cx, cy, r], i) => (
      <circle key={i} cx={cx} cy={cy} r={r} />
    ))}
  </g>
);

export const Cloud = ({pose, id = 'c'}: {pose: Partial<CloudPose>; id?: string}) => {
  const p = {...CLOUD_REST, ...pose};
  const sx = 1 / Math.sqrt(p.squash);
  const body = mix('#FAFCFE', '#A9B2BE', p.grey);
  const rim = mix('#C3CFDB', '#7D8794', p.grey);
  const shade = mix('#DCE5EE', '#8F99A6', p.grey);
  const cheek = mix('#F5A9A0', '#B79CA0', p.grey);
  const blink = Math.min(1, Math.max(0, p.blink));
  const [lx, ly] = p.look;
  const eye = (cx: number) => (
    <g transform={`translate(${cx + lx * 7} ${-12 + ly * 6})`}>
      <g transform={`scale(1 ${1 - blink * 0.9})`}>
        <ellipse cx="0" cy="0" rx="17" ry="24" fill={theme.ink} />
        <circle cx="5" cy="-9" r="6.5" fill="#fff" />
      </g>
    </g>
  );
  const brow = (cx: number, side: number) => (
    <path
      d={`M ${cx - 24} -50 Q ${cx} -60 ${cx + 24} -50`}
      transform={`translate(0 ${-p.brow * 12 + (p.grump > 0 ? 4 : 0)}) rotate(${side * p.grump * 18} ${cx} -52)`}
      fill="none"
      stroke={theme.ink}
      strokeWidth="8"
      strokeLinecap="round"
    />
  );
  const mouth = () => {
    const stroke = {fill: 'none', stroke: theme.ink, strokeWidth: 9, strokeLinecap: 'round' as const};
    switch (p.mouth) {
      case 'grin':
        return (
          <g>
            <path d="M -58 24 Q 0 92 58 24 Z" fill={theme.ink} />
            <path d="M -50 28 Q 0 40 50 28 L 46 40 Q 0 50 -46 40 Z" fill="#fff" />
            <path d="M -26 62 Q 0 50 26 62 Q 0 76 -26 62 Z" fill="#F08C8C" />
          </g>
        );
      case 'open': {
        const h = 8 + p.open * 40;
        return (
          <g>
            <ellipse cx="0" cy={34 + h * 0.35} rx={30 + p.open * 14} ry={h} fill={theme.ink} />
            <ellipse cx="0" cy={34 + h * 0.9} rx={16 + p.open * 8} ry={h * 0.35} fill="#F08C8C" />
          </g>
        );
      }
      case 'frown':
        return <path d="M -40 58 Q 0 26 40 58" {...stroke} />;
      case 'o':
        return <ellipse cx="0" cy="44" rx="13" ry="16" fill={theme.ink} />;
      default:
        return <path d="M -46 28 Q 0 72 46 28" {...stroke} />;
    }
  };
  return (
    <g transform={`translate(${p.x} ${p.y}) rotate(${p.tilt}) scale(${p.scale * sx} ${p.scale * p.squash})`}>
      <defs>
        <clipPath id={`cloud-${id}`}>
          <Shapes />
        </clipPath>
      </defs>
      {/* rim, then body: an outline around the union of the puffs */}
      <Shapes fill={rim} stroke={rim} strokeWidth="18" />
      <Shapes fill={body} />
      <g clipPath={`url(#cloud-${id})`}>
        <ellipse cx="20" cy="130" rx="360" ry="80" fill={shade} />
        <ellipse cx="-120" cy="-150" rx="150" ry="70" fill="#fff" opacity={0.7 * (1 - p.grey)} />
      </g>
      {/* face */}
      <ellipse cx={-118} cy={26} rx={30 + p.puff * 26} ry={18 + p.puff * 22} fill={cheek} opacity={0.5 + p.puff * 0.2} />
      <ellipse cx={118} cy={26} rx={30 + p.puff * 26} ry={18 + p.puff * 22} fill={cheek} opacity={0.5 + p.puff * 0.2} />
      {p.puff > 0.05 ? (
        <>
          <ellipse cx={-112} cy={18} rx={10 * p.puff} ry={6 * p.puff} fill="#fff" opacity="0.5" />
          <ellipse cx={124} cy={18} rx={10 * p.puff} ry={6 * p.puff} fill="#fff" opacity="0.5" />
        </>
      ) : null}
      {eye(-62)}
      {eye(62)}
      {brow(-62, 1)}
      {brow(62, -1)}
      {p.puff > 0.3 ? <ellipse cx="0" cy="46" rx="9" ry="7" fill={theme.ink} /> : mouth()}
      {/* reading glasses slide down onto the eyes */}
      {p.glasses > 0.01 ? (
        <g transform={`translate(0 ${-(1 - p.glasses) * 140})`} opacity={Math.min(1, p.glasses * 2)}>
          {[-62, 62].map((cx) => (
            <g key={cx}>
              <circle cx={cx} cy="-10" r="38" fill="#EAF6FF" fillOpacity="0.25" stroke={theme.ink} strokeWidth="8" />
              <path d={`M ${cx - 22} -28 Q ${cx - 10} -38 ${cx + 4} -36`} fill="none" stroke="#fff" strokeWidth="5" strokeLinecap="round" opacity="0.8" />
            </g>
          ))}
          <path d="M -24 -14 Q 0 -26 24 -14" fill="none" stroke={theme.ink} strokeWidth="8" strokeLinecap="round" />
          <path d="M -100 -14 L -150 -26 M 100 -14 L 150 -26" stroke={theme.ink} strokeWidth="7" strokeLinecap="round" />
        </g>
      ) : null}
    </g>
  );
};

/** A puffy cloud arm from (x0, y0) to a hand at (x1, y1), in world units, drawn with the cloud's rim. */
export const CloudArm = ({x0, y0, x1, y1, grey = 0, width = 46}: {x0: number; y0: number; x1: number; y1: number; grey?: number; width?: number}) => {
  const body = mix('#FAFCFE', '#A9B2BE', grey);
  const rim = mix('#C3CFDB', '#7D8794', grey);
  const mx = (x0 + x1) / 2;
  const my = Math.min(y0, y1) - 30;
  const d = `M ${x0} ${y0} Q ${mx} ${my} ${x1} ${y1}`;
  return (
    <g>
      <path d={d} fill="none" stroke={rim} strokeWidth={width + 16} strokeLinecap="round" />
      <path d={d} fill="none" stroke={body} strokeWidth={width} strokeLinecap="round" />
      <circle cx={x1} cy={y1} r={width * 0.72 + 8} fill={rim} />
      <circle cx={x1} cy={y1} r={width * 0.72} fill={body} />
    </g>
  );
};
