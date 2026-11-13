// Cogi as a puppet: the 24 shapes of site/assets/cogi.svg, grouped into parts that move about their own
// pivots. Coordinates are the logo's 200x200 space; (123, 182) is the point between the feet, which is
// where `x`, `y` place Cogi in the world. Everything is a pure function of the pose.
import {theme} from '../kit/theme';
import {blinkAt, wobble} from '../kit/motion';

const C = theme.cogi;
const A = theme.acorn;

export type CogiMouth = 'smile' | 'open' | 'o' | 'smug' | 'grin';

export type CogiPose = {
  x: number;
  y: number;
  scale: number;
  /** 1 faces right (as the logo), -1 faces left. */
  flip: number;
  /** Whole-body rotation in degrees about the feet. */
  lean: number;
  /** 1 neutral; below 1 squashes (wider), above 1 stretches (taller). */
  squash: number;
  /** Height above the ground (up-negative), so the shadow stays put. */
  lift: number;
  headRot: number;
  headY: number;
  earL: number;
  earR: number;
  tail: number;
  /** Extra curl of the tail tip, -1..1. */
  tailCurl: number;
  eye: [number, number];
  blink: number;
  /** Upper lid 0..1, for smug and sleepy looks. */
  lid: number;
  /** Brow -1 (lowered, determined) .. 1 (raised, surprised). */
  brow: number;
  /** Cheek pouch 0..1, for stuffing acorns. */
  cheek: number;
  mouth: CogiMouth;
  /** Paws 0 at the chest .. 1 held forward (presenting) .. 2 raised high .. -1 tucked back (wind-up). */
  paws: number;
  acorn: boolean;
  acornLabel?: string;
  /** Feet lift for scurrying, -1..1 (alternating). */
  run: number;
  /** Eye sparkle 0..1. */
  sparkle: number;
};

export const COGI_REST: CogiPose = {
  x: 0, y: 0, scale: 1, flip: 1, lean: 0, squash: 1, lift: 0, headRot: 0, headY: 0, earL: 0, earR: 0, tail: 0, tailCurl: 0,
  eye: [0, 0], blink: 0, lid: 0, brow: 0, cheek: 0, mouth: 'smile', paws: 0, acorn: true, run: 0, sparkle: 0,
};

/** The life underneath any pose: breathing, blinks, ear flicks and a lazy tail. */
export const idleCogi = (frame: number, seed = 1): Partial<CogiPose> => {
  const breath = Math.sin((frame / 30) * Math.PI * 0.9 + seed);
  const flick = Math.max(0, Math.sin((frame + seed * 17) / 11)) ** 12;
  return {
    squash: 1 + breath * 0.012,
    headRot: wobble(frame, 0.35, 2.5, `h${seed}`),
    tail: wobble(frame, 0.45, 6, `t${seed}`),
    tailCurl: wobble(frame, 0.6, 0.35, `c${seed}`),
    earL: -flick * 14,
    earR: wobble(frame, 0.5, 2, `e${seed}`),
    blink: blinkAt(frame, seed),
  };
};

const Mouth = ({m}: {m: CogiMouth}) => {
  const stroke = {fill: 'none', stroke: C.eye, strokeWidth: 1.6, strokeLinecap: 'round' as const};
  switch (m) {
    case 'smug':
      return <path d="M163 103 Q168 104.5 173.5 99" {...stroke} />;
    case 'grin':
      return (
        <>
          <path d="M162.5 100.5 Q168 109 173.5 99.5 Z" fill={C.eye} />
          <path d="M164.5 103 Q168 107.5 171.5 102.5 Z" fill={C.pink} />
        </>
      );
    case 'open':
      return (
        <>
          <ellipse cx="168" cy="104.5" rx="4.2" ry="5" fill={C.eye} />
          <ellipse cx="168" cy="106.5" rx="2.6" ry="2.2" fill={C.pink} />
        </>
      );
    case 'o':
      return <ellipse cx="168.5" cy="104" rx="2.3" ry="2.8" fill={C.eye} />;
    default:
      return <path d="M164 102 Q168 105 172 101" {...stroke} />;
  }
};

export const AcornShape = ({label}: {label?: string}) => (
  <>
    <ellipse cx="151" cy="133" rx="10" ry="12" fill={A.nut} />
    <ellipse cx="148" cy="130" rx="3" ry="5" fill={A.light} opacity={0.7} />
    <path d="M139 127 Q151 111 163 127 Z" fill={A.cap} />
    <rect x="149.5" y="112" width="3" height="6" rx="1.5" fill={A.cap} />
    {label ? (
      <text x="151" y="139" fontSize="5" textAnchor="middle" fontFamily={theme.fonts.display} fontWeight={700} fill={theme.cream}>
        {label}
      </text>
    ) : null}
  </>
);

export const Cogi = ({pose}: {pose: Partial<CogiPose>}) => {
  const p = {...COGI_REST, ...pose};
  const sx = 1 / Math.sqrt(p.squash);
  const blink = Math.min(1, Math.max(p.blink, 0));
  const feetA = Math.max(0, p.run) * 6;
  const feetB = Math.max(0, -p.run) * 6;
  const pawLift = p.paws;
  const shadowScale = 1 / (1 + Math.abs(p.lift) / 140);
  return (
    <g transform={`translate(${p.x} ${p.y}) scale(${p.scale * p.flip} ${p.scale}) translate(-123 -182)`}>
      {/* ground shadow, stays on the ground */}
      <ellipse cx="116" cy="186" rx={60 * shadowScale} ry={6 * shadowScale} fill="#2B1D12" opacity={0.13 * shadowScale} />
      <g transform={`translate(0 ${p.lift}) rotate(${p.lean} 123 182) translate(123 182) scale(${sx} ${p.squash}) translate(-123 -182)`}>
        {/* feet */}
        <ellipse cx="106" cy={180 - feetA} rx="15" ry="6" fill={C.dark} />
        <ellipse cx="140" cy={181 - feetB} rx="15" ry="6" fill={C.dark} />
        {/* tail: rotates at its base, the tip curls a little more */}
        <g transform={`rotate(${p.tail} 112 162)`}>
          <path d="M100 170 C50 174 16 134 24 88 C30 50 62 20 100 22 C130 24 144 52 128 68 C117 78 99 71 101 57 C102 50 109 47 114 51 C108 44 98 46 96 56 C94 70 104 84 112 98 L114 160 Z" fill={C.dark} />
          <path d="M96 158 C60 160 36 128 42 92 C47 62 70 38 98 37 C112 37 122 45 121 55 C112 43 92 43 82 56 C70 74 72 112 100 140 Z" fill={C.light} />
          <g transform={`rotate(${p.tailCurl * 8} 104 62)`}>
            <path d="M91 43 C90 74 104 88 116 100 L128 64 C120 54 106 38 91 43 Z" fill={C.dark} />
          </g>
        </g>
        {/* body */}
        <ellipse cx="118" cy="140" rx="36" ry="42" fill={C.mid} />
        <ellipse cx="131" cy="147" rx="21" ry="30" fill={C.belly} />
        {/* head */}
        <g transform={`translate(0 ${p.headY}) rotate(${p.headRot} 130 112)`}>
          <g transform={`rotate(${p.earR} 124 66)`}>
            <path d="M120 68 L114 38 Q130 44 138 60 Z" fill={C.dark} />
          </g>
          <circle cx="138" cy="88" r="30" fill={C.mid} />
          <g transform={`rotate(${p.earL} 136 62)`}>
            <path d="M130 64 L131 34 Q147 42 150 62 Z" fill={C.mid} />
            <path d="M134 60 L135 43 Q144 48 146 60 Z" fill={C.pink} />
          </g>
          {/* cheek pouch grows when stuffed */}
          <ellipse cx="160" cy="97" rx="15" ry="12" fill={C.mid} />
          <ellipse cx="159" cy="101" rx="12" ry="9" fill={C.belly} />
          {/* cheek pouch: bulges past the jaw when stuffed */}
          {p.cheek > 0.01 ? (
            <g>
              <ellipse cx={150 + p.cheek * 1} cy={104 + p.cheek * 5} rx={7 + p.cheek * 13} ry={6 + p.cheek * 11} fill={C.light} />
              <ellipse cx={146 + p.cheek * 1} cy={100 + p.cheek * 3} rx={3 + p.cheek * 5} ry={2 + p.cheek * 3} fill="#fff" opacity={0.35} />
            </g>
          ) : null}
          {/* eye */}
          <g transform={`translate(${p.eye[0]} ${p.eye[1]})`}>
            <g transform={`translate(150 88) scale(1 ${1 - blink * 0.92}) translate(-150 -88)`}>
              <ellipse cx="150" cy="83" rx="5" ry="6" fill={C.eye} />
              <circle cx="152" cy="81" r={1.8 + p.sparkle * 0.8} fill="#fff" />
              {p.sparkle > 0.05 ? <circle cx="148.3" cy="85.6" r={1.1 * p.sparkle} fill="#fff" /> : null}
            </g>
          </g>
          {p.lid > 0.01 ? (
            <>
              <path d={`M143.5 ${76.5} L156.5 ${76.5} L156.5 ${76.5 + p.lid * 7} Q150 ${78 + p.lid * 7.5} 143.5 ${76.5 + p.lid * 7} Z`} fill={C.mid} />
              <path d={`M144 ${76.5 + p.lid * 7} Q150 ${78 + p.lid * 7.5} 156 ${76.5 + p.lid * 7}`} fill="none" stroke={C.eye} strokeWidth="1.3" strokeLinecap="round" />
            </>
          ) : null}
          {/* brow */}
          <path
            d="M144.5 73.5 Q150 70.5 155.5 73"
            transform={`translate(0 ${-p.brow * 2.6}) rotate(${-p.brow * 9} 150 72)`}
            fill="none"
            stroke={C.eye}
            strokeWidth="1.9"
            strokeLinecap="round"
            opacity={0.85}
          />
          <ellipse cx="172" cy="94" rx="3.6" ry="2.8" fill={C.eye} />
          <Mouth m={p.mouth} />
          <circle cx="146" cy="99" r="5" fill={C.pink} opacity=".6" />
        </g>
        {/* paws and acorn: lift forward and up to present */}
        <g transform={`translate(${pawLift * 22} ${-pawLift * 8 - Math.max(0, pawLift - 1) * 30}) rotate(${-pawLift * 10} 145 128)`}>
          {p.acorn ? <AcornShape label={p.acornLabel} /> : null}
          <ellipse cx="141" cy="134" rx="6.5" ry="5" fill={C.mid} />
          <ellipse cx="161" cy="136" rx="6.5" ry="5" fill={C.mid} />
        </g>
      </g>
    </g>
  );
};
