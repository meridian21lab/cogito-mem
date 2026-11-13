// The film finish laid over every frame: a soft vignette, a fine animated grain, and an optional warm
// light leak that drifts across (used on reveals and the tagline).
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';

export const Finish = ({leaks = []}: {leaks?: {from: number; dur: number}[]}) => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{pointerEvents: 'none'}}>
      {leaks.map(({from, dur}, i) => {
        const t = (frame - from) / dur;
        if (t < 0 || t > 1) return null;
        const o = Math.sin(t * Math.PI) * 0.55;
        const x = interpolate(t, [0, 1], [-30, 110]);
        return (
          <AbsoluteFill
            key={i}
            style={{
              mixBlendMode: 'screen',
              opacity: o,
              background: `radial-gradient(ellipse 55% 40% at ${x}% 30%, rgba(255,190,110,0.95), rgba(255,140,60,0.45) 45%, rgba(255,120,40,0) 75%)`,
            }}
          />
        );
      })}
      <AbsoluteFill style={{background: 'radial-gradient(ellipse 78% 62% at 50% 46%, rgba(0,0,0,0) 58%, rgba(43,29,18,0.30) 100%)'}} />
      <AbsoluteFill style={{mixBlendMode: 'overlay', opacity: 0.09}}>
        <svg width="100%" height="100%">
          <filter id="grain">
            <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed={frame % 12} stitchTiles="stitch" />
            <feColorMatrix type="saturate" values="0" />
          </filter>
          <rect width="100%" height="100%" filter="url(#grain)" />
        </svg>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
