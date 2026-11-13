import {AbsoluteFill, Composition} from 'remotion';
import {FORMATS, FPS} from './kit/formats';
import {loadFonts, theme} from './kit/theme';

loadFonts();

const Placeholder = () => <AbsoluteFill style={{background: theme.cream}} />;

export const Root = () => (
  <>
    <Composition id="placeholder" component={Placeholder} durationInFrames={FPS} fps={FPS} width={FORMATS.shorts.width} height={FORMATS.shorts.height} />
  </>
);
