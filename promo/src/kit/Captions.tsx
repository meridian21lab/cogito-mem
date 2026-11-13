// Word-by-word captions: the current phrase (up to 4-5 words, broken at sentence ends), the spoken word lit in
// orange with a small pop. Placed at the format's caption height, inside the safe zones.
import {useCurrentFrame, useVideoConfig} from 'remotion';
import {FORMATS, type FormatId} from './formats';
import {springAt} from './motion';
import {theme} from './theme';
import type {Timeline} from './timeline';

type Word = {text: string; from: number; to: number};

/** Phrases of up to 4 words, broken at sentence ends and after commas; a lone last word joins the phrase before it. */
const chunk = (words: Word[]) => {
  const out: Word[][] = [];
  let cur: Word[] = [];
  for (const w of words) {
    cur.push(w);
    if (cur.length === 4 || (/[.!?]$/.test(w.text) && !/\.\.\.$/.test(w.text)) || (cur.length >= 2 && /,$/.test(w.text))) {
      out.push(cur);
      cur = [];
    }
  }
  if (cur.length) out.push(cur);
  for (let i = out.length - 1; i > 0; i--) {
    if (out[i].length === 1 && out[i - 1].length <= 4) {
      out[i - 1].push(...out[i]);
      out.splice(i, 1);
    }
  }
  return out;
};

export const Captions = ({tl, format, hide = []}: {tl: Timeline; format: FormatId; hide?: string[]}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const line = tl.lines.find((l) => frame >= l.from - 2 && frame < l.to + 8);
  if (!line || hide.includes(line.id)) return null;
  const groups = chunk(line.words);
  const g = [...groups].reverse().find((c) => frame >= c[0].from - 2) ?? groups[0];
  const start = g[0].from - 2;
  const pop = springAt(frame, start, fps, {damping: 13, stiffness: 260, mass: 0.6});
  const {captionY, width} = FORMATS[format];
  return (
    <div
      style={{
        position: 'absolute',
        left: 110,
        width: width - 260,
        top: captionY - 70,
        display: 'flex',
        justifyContent: 'center',
        flexWrap: 'wrap',
        gap: '0 36px',
        transform: `scale(${0.85 + pop * 0.15}) translateY(${(1 - pop) * 18}px)`,
        opacity: Math.min(1, pop * 1.5),
      }}
    >
      {g.map((w, i) => {
        const on = frame >= w.from && (i === g.length - 1 || frame < g[i + 1].from);
        const lit = springAt(frame, w.from, fps, {damping: 12, stiffness: 300, mass: 0.5});
        return (
          <span
            key={i}
            style={{
              fontFamily: theme.fonts.display,
              fontWeight: 700,
              fontSize: 84,
              lineHeight: 1.12,
              color: on ? theme.orange : frame >= w.from ? theme.paper : 'rgba(255,251,244,0.9)',
              WebkitTextStroke: `11px ${theme.ink}`,
              paintOrder: 'stroke fill',
              textShadow: '0 8px 0 rgba(43,29,18,0.35)',
              display: 'inline-block',
              transform: `scale(${on ? 1 + 0.07 * Math.min(1, lit) : 1})`,
            }}
          >
            {w.text.replace(/\.\.\.$/, '…')}
          </span>
        );
      })}
    </div>
  );
};
