// Goldie the goldfish: the cheerful, sincere, forgetful AI assistant. Never mean, never stupid, never drawn
// as Claude. Drawn in Cogi's flat style, in yellow-gold so it never reads as a second Cogi. Native space is
// 200x140 facing right; (100, 70) is the body centre, which is where `x`, `y` place Goldie.
import {theme} from '../kit/theme';
import {blinkAt} from '../kit/motion';

const G = theme.goldie;

export type GoldieMouth = 'smile' | 'o' | 'flat' | 'grin';

export type GoldiePose = {
  x: number;
  y: number;
  scale: number;
  flip: number;
  /** Body tilt in degrees. */
  tilt: number;
  /** Swim phase in cycles; the tail and fins wave from it. */
  swim: number;
  /** How hard the tail beats, 0..1.5. */
  beat: number;
  blink: number;
  /** 0 bright eyes .. 1 the vacant, forgotten-everything stare. */
  blank: number;
  mouth: GoldieMouth;
  /** 0..1 happy sparkle in the eyes and a blush. */
  sparkle: number;
  /** Pupil offset in the eye, px in native space. */
  look: [number, number];
  squash: number;
};

export const GOLDIE_REST: GoldiePose = {
  x: 0, y: 0, scale: 1, flip: 1, tilt: 0, swim: 0, beat: 1, blink: 0, blank: 0, mouth: 'smile', sparkle: 0, look: [0, 0], squash: 1,
};

/** Hovering in the bowl: slow bob, gentle tail, blinks. */
export const idleGoldie = (frame: number, seed = 2): Partial<GoldiePose> => ({
  swim: frame / 26,
  tilt: Math.sin(frame / 22 + seed) * 3,
  blink: blinkAt(frame, seed),
});

const Mouth = ({m}: {m: GoldieMouth}) => {
  switch (m) {
    case 'o':
      return <ellipse cx="171" cy="80" rx="4" ry="5" fill={G.eye} />;
    case 'flat':
      return <path d="M163 82 L174 81" stroke={G.eye} strokeWidth="2.4" strokeLinecap="round" />;
    case 'grin':
      return (
        <>
          <path d="M160 79 Q168 92 176 78 Z" fill={G.eye} />
          <path d="M163 83 Q168 89 173 82 Z" fill="#F28C8C" />
        </>
      );
    default:
      return <path d="M161 80 Q168 87 175 79" fill="none" stroke={G.eye} strokeWidth="2.4" strokeLinecap="round" />;
  }
};

export const Goldie = ({pose}: {pose: Partial<GoldiePose>}) => {
  const p = {...GOLDIE_REST, ...pose};
  const w = Math.sin(p.swim * Math.PI * 2);
  const w2 = Math.sin(p.swim * Math.PI * 2 - 1.1);
  const tailRot = w * 16 * p.beat;
  const pupil = 7 - p.blank * 4.6;
  const blink = Math.min(1, p.blink);
  return (
    <g transform={`translate(${p.x} ${p.y}) rotate(${p.tilt}) scale(${p.scale * p.flip / Math.sqrt(p.squash)} ${p.scale * p.squash}) translate(-100 -70)`}>
      {/* tail fin: two flowing lobes, waving from the base */}
      <g transform={`rotate(${tailRot} 64 70)`}>
        <path
          d={`M66 70 C52 ${58 + w2 * 3} 34 ${30 + w2 * 8} 16 ${32 + w2 * 10} C26 ${50 + w2 * 6} 28 62 36 70 C28 78 26 ${90 - w2 * 6} 16 ${108 - w2 * 10} C34 ${110 - w2 * 8} 52 ${82 - w2 * 3} 66 70 Z`}
          fill={G.fin}
          opacity={0.95}
        />
        <path d={`M62 70 C50 ${62 + w2 * 2} 40 ${46 + w2 * 5} 28 ${42 + w2 * 7}`} fill="none" stroke={G.finEdge} strokeWidth="2" opacity={0.55} strokeLinecap="round" />
        <path d={`M62 70 C50 ${78 - w2 * 2} 40 ${94 - w2 * 5} 28 ${98 - w2 * 7}`} fill="none" stroke={G.finEdge} strokeWidth="2" opacity={0.55} strokeLinecap="round" />
      </g>
      {/* dorsal fin */}
      <path d={`M94 38 C100 ${18 + w * 3} 118 ${12 + w * 4} 134 ${22 + w * 2} C128 30 120 34 116 40 Z`} fill={G.fin} />
      {/* body */}
      <path d="M60 70 C60 44 92 30 126 33 C156 36 178 54 178 72 C178 90 158 106 128 108 C94 111 60 98 60 70 Z" fill={G.body} />
      <path d="M70 82 C84 100 116 106 140 102 C156 99 168 92 174 82 C160 94 120 98 96 92 C84 89 76 86 70 82 Z" fill={G.belly} />
      {/* a few scale arcs */}
      <g fill="none" stroke={G.finEdge} strokeWidth="1.6" opacity={0.35} strokeLinecap="round">
        <path d="M100 52 Q106 58 100 64" />
        <path d="M112 48 Q118 54 112 60" />
        <path d="M110 66 Q116 72 110 78" />
        <path d="M98 70 Q104 76 98 82" />
      </g>
      {/* side fin */}
      <path d={`M118 84 C112 ${96 + w * 4} 100 ${102 + w * 5} 94 ${98 + w * 3} C100 92 108 88 118 84 Z`} fill={G.fin} />
      {/* cheek */}
      <circle cx="150" cy="80" r="7" fill="#F28C8C" opacity={0.35 + p.sparkle * 0.35} />
      {/* eye: big and sincere */}
      <g transform={`translate(146 60) scale(1 ${1 - blink * 0.9}) translate(-146 -60)`}>
        <circle cx="146" cy="60" r="14" fill="#fff" />
        <circle cx={147 + p.look[0]} cy={61 + p.look[1]} r={pupil} fill={G.eye} />
        <circle cx={150 + p.look[0] - p.blank * 2} cy={57 + p.look[1]} r={2.6 * (1 - p.blank * 0.7) + p.sparkle * 1.2} fill="#fff" />
        {p.sparkle > 0.05 ? <circle cx={144 + p.look[0]} cy={64 + p.look[1]} r={1.6 * p.sparkle} fill="#fff" /> : null}
      </g>
      <Mouth m={p.mouth} />
    </g>
  );
};
