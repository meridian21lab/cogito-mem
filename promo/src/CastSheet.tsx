// A still sheet of the cast and the world, for checking the drawings before they are animated.
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {Cogi, idleCogi, type CogiPose} from './cast/Cogi';
import {Goldie, idleGoldie, type GoldiePose} from './cast/Goldie';
import {Camera, Layer} from './kit/Camera';
import {Bowl, MessageBubble} from './world/Bowl';
import {Desk, Hands, Laptop, Mug} from './world/Desk';
import {FarTrees, Ground, MidTrees, Sky} from './world/Backdrop';
import {Tree} from './world/Tree';
import {theme} from './kit/theme';

const cogiPoses: Partial<CogiPose>[] = [
  {},
  {mouth: 'grin', paws: 1, sparkle: 1, brow: 0.6},
  {lid: 0.55, mouth: 'smug', brow: -0.6, tail: 12},
  {cheek: 1, mouth: 'o', blink: 0},
  {squash: 0.78, lean: -8, brow: 1, mouth: 'open'},
  {squash: 1.18, lift: -60, run: 1, lean: 12},
];

const goldiePoses: Partial<GoldiePose>[] = [{}, {blank: 1, mouth: 'flat'}, {sparkle: 1, mouth: 'grin'}, {mouth: 'o', tilt: -12}];

export const CastSheet = () => {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill style={{background: theme.cream}}>
      <svg width={1080} height={1920} viewBox="0 0 1080 1920">
        {cogiPoses.map((p, i) => (
          <Cogi key={i} pose={{...idleCogi(frame, i), x: 190 + (i % 3) * 350, y: 330 + Math.floor(i / 3) * 330, scale: 1.25, ...p}} />
        ))}
        {goldiePoses.map((p, i) => (
          <Goldie key={i} pose={{...idleGoldie(frame), x: 160 + i * 255, y: 820, scale: 1.05, ...p}} />
        ))}
        <text x="40" y="60" fontFamily={theme.fonts.display} fontWeight={700} fontSize="40" fill={theme.ink}>
          Cast sheet
        </text>
      </svg>
      <div style={{position: 'absolute', top: 960, left: 0, width: 1080, height: 960, overflow: 'hidden'}}>
        <div style={{position: 'absolute', top: -480, left: 0}}>
          <Camera shot={{x: 900, y: 1000, zoom: 0.5}} prev={{x: 900, y: 1000, zoom: 0.5}} format="shorts">
            <Layer depth={0.05}>
              <Sky />
            </Layer>
            <Layer depth={0.3}>
              <FarTrees />
            </Layer>
            <Layer depth={0.6}>
              <MidTrees frame={frame} />
            </Layer>
            <Layer>
              <Ground y={1600} />
              <Tree x={1650} y={1240} ground={1640} frame={frame} shelf={7} tags={7} sign={1} />
              <Desk x0={-300} x1={1460} top={1240} />
              <Laptop x={400} y={1240} typed="The staging server is called acorn." caret={false} reply={1} />
              <Hands x={400} y={1215} typing={0} />
              <Bowl x={930} y={1240} frame={frame}>
                <Goldie pose={{...idleGoldie(frame), x: 0, y: -210, scale: 1}} />
                <MessageBubble x={0} y={-330} text={['staging server:', 'acorn']} frame={frame} scale={0.8} />
              </Bowl>
              <Mug x={1200} y={1240} frame={frame} />
              <Cogi pose={{...idleCogi(frame), x: 1650, y: 1240, scale: 1.3, flip: -1}} />
            </Layer>
          </Camera>
        </div>
      </div>
    </AbsoluteFill>
  );
};
