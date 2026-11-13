// The developer's desk at the forest edge: the desk, the laptop with its chat, the developer's hands (the
// only part of the developer we see), and a mug. All anchored at their bottom centre on the desk top.
import {theme} from '../kit/theme';

const Wd = theme.wood;

export const Desk = ({x0, x1, top}: {x0: number; x1: number; top: number}) => (
  <g>
    <rect x={x0} y={top} width={x1 - x0} height={46} fill={Wd.top} />
    <rect x={x0} y={top} width={x1 - x0} height={7} fill="#E0A874" />
    <rect x={x0} y={top + 46} width={x1 - x0} height={900} fill={Wd.edge} />
    <rect x={x0} y={top + 46} width={x1 - x0} height={18} fill={Wd.dark} opacity="0.55" />
    {Array.from({length: 9}, (_, i) => (
      <path key={i} d={`M ${x0 + 60 + i * 190} ${top + 18} q 60 ${i % 2 ? 6 : -5} 130 0`} stroke={Wd.edge} strokeWidth="3" fill="none" opacity="0.35" strokeLinecap="round" />
    ))}
  </g>
);

const wrap = (text: string, max: number) => {
  const lines: string[] = [];
  let cur = '';
  for (const w of text.split(' ')) {
    if ((cur + ' ' + w).trim().length > max && cur) {
      lines.push(cur);
      cur = w;
    } else cur = (cur + ' ' + w).trim();
  }
  if (cur) lines.push(cur);
  return lines;
};

/**
 * The laptop seen from the developer's seat. `typed` is the message typed so far; `reply` shows the
 * assistant's "Got it!"; `cleared` 0..1 wipes the chat away for a new one.
 */
export const Laptop = ({x, y, typed, caret, reply = 0, cleared = 0, sent = 0}: {x: number; y: number; typed: string; caret: boolean; reply?: number; cleared?: number; sent?: number}) => {
  const sw = 640;
  const sh = 420;
  const top = -75 - sh;
  const lines = wrap(typed, 20);
  const bubbleH = 40 + Math.max(1, lines.length) * 46;
  const wipe = cleared * (sh - 70);
  return (
    <g transform={`translate(${x} ${y})`}>
      <ellipse cx="0" cy="4" rx="380" ry="16" fill={theme.ink} opacity="0.14" />
      {/* screen */}
      <rect x={-sw / 2} y={top} width={sw} height={sh} rx="26" fill={theme.ink} />
      <rect x={-sw / 2 + 18} y={top + 18} width={sw - 36} height={sh - 36} rx="12" fill={theme.paper} />
      <g>
        <rect x={-sw / 2 + 18} y={top + 18} width={sw - 36} height="52" rx="12" fill={theme.sand} />
        {[0, 1, 2].map((i) => (
          <circle key={i} cx={-sw / 2 + 46 + i * 26} cy={top + 44} r="7.5" fill={['#E8A07A', '#E8C77A', '#A9C98E'][i]} />
        ))}
        <text x="0" y={top + 53} textAnchor="middle" fontFamily={theme.fonts.display} fontWeight={700} fontSize="26" fill={theme.ink} opacity="0.7">
          {cleared > 0.5 ? 'New chat' : 'Chat'}
        </text>
      </g>
      <g opacity={1 - cleared}>
        {typed ? (
          <g transform={`translate(${sw / 2 - 48} ${top + 100 - sent * 6})`}>
            <rect x={-430} y="0" width="430" height={bubbleH} rx="26" fill={theme.orange} />
            {lines.map((l, i) => (
              <text key={i} x="-405" y={58 + i * 46} fontFamily={theme.fonts.body} fontSize="36" fill={theme.paper}>
                {l}
                {caret && i === lines.length - 1 ? '|' : ''}
              </text>
            ))}
          </g>
        ) : null}
        {reply > 0 ? (
          <g transform={`translate(${-sw / 2 + 48} ${top + 130 + bubbleH}) scale(${reply})`}>
            <rect x="0" y="0" width="210" height="76" rx="24" fill={theme.sand} />
            <text x="28" y="50" fontFamily={theme.fonts.body} fontSize="36" fill={theme.ink}>
              Got it!
            </text>
          </g>
        ) : null}
      </g>
      {cleared > 0 && cleared < 1 ? <rect x={-sw / 2 + 18} y={top + 70} width={sw - 36} height={wipe} fill={theme.paper} /> : null}
      {/* base and keyboard */}
      <path d={`M ${-sw / 2 - 10} -75 L ${sw / 2 + 10} -75 L ${sw / 2 + 60} 0 L ${-sw / 2 - 60} 0 Z`} fill="#E6D8C3" />
      <path d={`M ${-sw / 2 - 60} 0 L ${sw / 2 + 60} 0 L ${sw / 2 + 60} 10 L ${-sw / 2 - 60} 10 Z`} fill="#CDBBA2" />
      {Array.from({length: 3}, (_, r) => (
        <path key={r} d={`M ${-sw / 2 + 10 - r * 14} ${-62 + r * 18} L ${sw / 2 - 10 + r * 14} ${-62 + r * 18}`} stroke="#CDBBA2" strokeWidth="10" strokeDasharray="34 9" />
      ))}
    </g>
  );
};

const Hand = ({side, tap}: {side: 1 | -1; tap: number}) => (
  <g transform={`scale(${side} 1)`}>
    {/* forearm and sleeve, running down and out to the frame's corner */}
    <path d="M 44 58 C 10 200 -110 420 -250 660 L -20 700 C 50 470 120 250 150 58 Z" fill={theme.sleeve} />
    <path d="M 44 58 C 30 110 22 140 14 170 L 136 190 C 142 150 146 110 150 58 Z" fill={theme.skin} />
    <path d="M 12 176 L 138 196 L 128 236 L -2 212 Z" fill="#3F5966" />
    {/* hand */}
    <ellipse cx="95" cy="30" rx="62" ry="44" fill={theme.skin} />
    {[0, 1, 2, 3].map((i) => (
      <ellipse key={i} cx={52 + i * 28} cy={-10 + (i % 2 === (tap > 0 ? 0 : 1) ? Math.abs(tap) * 10 : 0)} rx="14" ry="22" fill={theme.skin} />
    ))}
    <ellipse cx="155" cy="40" rx="15" ry="24" transform="rotate(-30 155 40)" fill={theme.skin} />
    <ellipse cx="95" cy="48" rx="40" ry="14" fill="#E0A87E" opacity="0.45" />
  </g>
);

/** Both hands on the keyboard; `typing` is a phase that makes the fingers tap (0 = resting). */
export const Hands = ({x, y, typing}: {x: number; y: number; typing: number}) => {
  const tL = typing ? Math.sin(typing * 9.1) : 0;
  const tR = typing ? Math.sin(typing * 8.3 + 1.7) : 0;
  return (
    <g transform={`translate(${x} ${y})`}>
      <g transform={`translate(-260 ${Math.abs(tL) * -6})`}>
        <Hand side={1} tap={tL} />
      </g>
      <g transform={`translate(260 ${Math.abs(tR) * -6})`}>
        <Hand side={-1} tap={tR} />
      </g>
    </g>
  );
};

export const Mug = ({x, y, frame}: {x: number; y: number; frame: number}) => (
  <g transform={`translate(${x} ${y})`}>
    <ellipse cx="6" cy="3" rx="80" ry="10" fill={theme.ink} opacity="0.14" />
    <path d="M 48 -110 C 100 -110 100 -40 48 -44" fill="none" stroke={theme.cream} strokeWidth="18" />
    <rect x="-62" y="-140" width="120" height="140" rx="18" fill={theme.cream} />
    <rect x="-62" y="-140" width="120" height="22" rx="10" fill="#EADBC4" />
    <g transform="translate(-2 -62) scale(0.9)">
      <ellipse cx="0" cy="6" rx="16" ry="19" fill={theme.acorn.nut} />
      <path d="M -19 -2 Q 0 -27 19 -2 Z" fill={theme.acorn.cap} />
    </g>
    {[0, 1, 2].map((i) => {
      const t = ((frame / 50 + i / 3) % 1);
      return (
        <path
          key={i}
          d={`M ${-24 + i * 22} -150 c 18 -30 -18 -50 0 -80`}
          transform={`translate(${Math.sin(frame / 20 + i) * 6} ${-t * 70})`}
          fill="none"
          stroke="#fff"
          strokeWidth="9"
          strokeLinecap="round"
          opacity={Math.sin(t * Math.PI) * 0.6}
        />
      );
    })}
  </g>
);
