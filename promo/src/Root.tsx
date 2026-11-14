import {Composition, Still} from 'remotion';
import {CastSheet} from './CastSheet';
import {Cover as Cover01, Film as Film01} from './films/01-claude-forgets/Film';
import {script as script01} from './films/01-claude-forgets/script';
import {Cover as Cover02, Film as Film02} from './films/02-stays-home/Film';
import {script as script02} from './films/02-stays-home/script';
import {filmMetadata} from './kit/film';
import {FORMATS, FPS, type FormatId} from './kit/formats';
import {loadFonts} from './kit/theme';

loadFonts();

const films = [
  {slug: 'claude-forgets', script: script01, component: Film01, cover: Cover01},
  {slug: 'stays-home', script: script02, component: Film02, cover: Cover02},
];

export const Root = () => (
  <>
    {films.flatMap(({slug, cover}) =>
      (Object.keys(FORMATS) as FormatId[]).map((format) => (
        <Still key={`${slug}-cover-${format}`} id={`${slug}-cover-${format}`} component={cover} width={FORMATS[format].width} height={FORMATS[format].height} defaultProps={{format}} />
      )),
    )}
    {films.flatMap(({slug, script, component}) =>
      (Object.keys(FORMATS) as FormatId[]).map((format) => (
        <Composition
          key={`${slug}-${format}`}
          id={`${slug}-${format}`}
          component={component}
          durationInFrames={FPS}
          fps={FPS}
          width={FORMATS[format].width}
          height={FORMATS[format].height}
          defaultProps={{format, mix: null}}
          calculateMetadata={filmMetadata(script)}
        />
      )),
    )}
    <Composition id="cast-sheet" component={CastSheet} durationInFrames={90} fps={FPS} width={1080} height={1920} />
  </>
);
