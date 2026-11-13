// The series ending, shared by every film: the tagline card ("Claude forgets." floats away word by word,
// "Cogi doesn't." slams in, Cogi hops and puffs up) and the end card (name, line, link pill, disclaimer),
// while Cogi tosses its acorn. Needs lines with ids 'tagline' ("Claude forgets. Cogi doesn't.") and 'cta'.
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {Cogi, idleCogi, type CogiPose} from '../cast/Cogi';
import {FORMATS, type FormatId} from '../kit/formats';
import {EASE, ease, hop, springAt} from '../kit/motion';
import {theme} from '../kit/theme';
import type {Timeline} from '../kit/timeline';
import {SparkleBurst} from './Particles';
import {SmallAcorn} from './Tree';

/** Where the end card points people, per cut. */
export type EndLink = {shorts: string; feed: string};
const LINK: EndLink = {shorts: 'Link in the description', feed: 'Link in the first comment'};

export const TitleCard = ({tl, format, link = LINK}: {tl: Timeline; format: FormatId; link?: EndLink}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const {width: W, height: H} = FORMATS[format];
  const forgets = tl.word('tagline', 'forgets');
  const cogiW = tl.word('tagline', 'Cogi');
  const claudeIn = springAt(frame, tl.word('tagline', 'Claude') - 2, fps);
  const drift = ease(frame, [forgets + 12, cogiW + 8], [0, 1], EASE.in);
  const slam = springAt(frame, cogiW - 3, fps, {damping: 9, stiffness: 220, mass: 0.8});
  const cy = H / 2 - (format === 'shorts' ? 120 : 60);
  const cta = tl.line('cta').from;
  const exit = ease(frame, [cta - 6, cta + 4], [0, 1], EASE.in);
  const toEnd = ease(frame, [cta - 2, cta + 8], [0, 1], EASE.out);
  // On the end card Cogi tosses its acorn and catches it.
  const toss = frame > cta + 12 ? ((frame - cta - 12) % 34) / 34 : 0;
  const tossing = toss > 0 && toss < 0.85;
  const tp = tossing ? toss / 0.85 : 0;
  const cogiX = W / 2 + 8;
  const cogiY = cy + 520 - toEnd * 150 + hop(frame, cogiW - 6, 16, 120).y;
  const scale = 2.3 - toEnd * 0.15;
  const cogi: Partial<CogiPose> = {
    ...idleCogi(frame, 5),
    x: cogiX,
    y: cogiY,
    squash: hop(frame, cogiW - 6, 16, 120).squash * (1 + 0.06 * slam) * (tossing && tp > 0.9 ? 0.94 : 1),
    scale,
    flip: 1,
    mouth: tossing ? 'grin' : 'smug',
    lid: tossing ? 0 : 0.45,
    brow: 0.5,
    paws: tossing ? 0.8 : 0.4,
    headRot: tossing ? -12 * Math.sin(tp * Math.PI) : 0,
    eye: tossing ? [1, -2 * Math.sin(tp * Math.PI)] : [0, 0],
    acorn: !tossing,
    tail: 10 * Math.sin(frame / 8),
  };
  const pawX = cogiX + 46 * scale;
  const pawY = cogiY - 55 * scale;
  return (
    <AbsoluteFill style={{background: theme.cream}}>
      <svg width={W} height={H} style={{position: 'absolute', inset: 0}}>
        <g transform={`translate(${W / 2} ${cy + 250}) rotate(${frame * 0.4})`} opacity={0.35}>
          {Array.from({length: 14}, (_, i) => (
            <path key={i} d="M 0 0 L -90 -1600 L 90 -1600 Z" transform={`rotate(${(i * 360) / 14})`} fill={i % 2 ? '#F6E0C4' : theme.cream} />
          ))}
        </g>
        <g opacity={1 - exit} transform={`translate(0 ${-exit * 220})`}>
          {['Claude', 'forgets.'].map((word, i) => {
            const d = Math.max(0, drift * 1.5 - i * 0.35);
            const x = W / 2 + (i === 0 ? -215 : 200);
            return (
              <text
                key={word}
                x={x}
                y={cy - 120 - d * 320}
                textAnchor="middle"
                fontFamily={theme.fonts.display}
                fontWeight={700}
                fontSize={104}
                fill={theme.ink}
                opacity={claudeIn * (1 - Math.min(1, d))}
                transform={`rotate(${d * (i ? 18 : -14)} ${x} ${cy - 120}) translate(0 ${(1 - claudeIn) * 40})`}
              >
                {word}
              </text>
            );
          })}
          <g transform={`translate(${W / 2} ${cy + 40}) scale(${0.4 + slam * 0.6}) rotate(${(1 - slam) * -6})`} opacity={Math.min(1, slam * 2)}>
            <text x="0" y="0" textAnchor="middle" fontFamily={theme.fonts.display} fontWeight={700} fontSize={140} fill={theme.orange} stroke={theme.ink} strokeWidth={11} paintOrder="stroke fill">
              Cogi doesn’t.
            </text>
          </g>
        </g>
        <Cogi pose={cogi} />
        {tossing ? <SmallAcorn x={pawX} y={pawY - 260 * 4 * tp * (1 - tp) + 40} s={2.2} rot={tp * 540} /> : null}
        {frame > cogiW - 6 ? <SparkleBurst frame={frame} at={cogiW} x={W / 2} y={cy + 20} spread={360} n={8} size={46} /> : null}
      </svg>
      <EndCard tl={tl} format={format} show={toEnd} link={link} />
    </AbsoluteFill>
  );
};

const EndCard = ({tl, format, show, link}: {tl: Timeline; format: FormatId; show: number; link: EndLink}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  if (show <= 0) return null;
  const cta = tl.line('cta').from;
  const a = springAt(frame, cta, fps);
  const b = springAt(frame, cta + 8, fps);
  const c = springAt(frame, tl.word('cta', 'Code') + 4, fps);
  const shorts = format === 'shorts';
  return (
    <AbsoluteFill style={{alignItems: 'center'}}>
      <div style={{position: 'absolute', top: shorts ? 300 : 90, width: '100%', textAlign: 'center'}}>
        <div style={{fontFamily: theme.fonts.display, fontWeight: 700, fontSize: 160, color: theme.ink, transform: `scale(${a})`, lineHeight: 1}}>Cogi</div>
        <div style={{fontFamily: theme.fonts.display, fontWeight: 700, fontSize: 58, lineHeight: 1.15, color: theme.ink, marginTop: 18, transform: `translateY(${(1 - b) * 30}px)`, opacity: b}}>
          Free, open-source memory
          <br />
          for <span style={{color: theme.rust}}>Claude Code</span>
        </div>
      </div>
      <div
        style={{
          position: 'absolute',
          top: shorts ? 1390 : 1000,
          padding: '20px 44px',
          borderRadius: 60,
          background: theme.ink,
          color: theme.paper,
          fontFamily: theme.fonts.display,
          fontWeight: 700,
          fontSize: 52,
          transform: `scale(${c})`,
        }}
      >
        {shorts ? link.shorts : link.feed}
      </div>
      <div style={{position: 'absolute', top: shorts ? 1520 : 1110, fontFamily: theme.fonts.body, fontSize: 32, maxWidth: 940, textAlign: 'center', color: theme.ink, opacity: 0.7 * c}}>
        An independent open-source project, not affiliated with Anthropic.
      </div>
    </AbsoluteFill>
  );
};
