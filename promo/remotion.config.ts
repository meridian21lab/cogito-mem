// Remotion CLI settings for the Cogi films. Renders are H.264 MP4 with AAC; loudness is normalised afterwards by scripts/render.sh.
import {Config} from '@remotion/cli/config';

Config.setVideoImageFormat('jpeg');
Config.setJpegQuality(92);
Config.setCodec('h264');
Config.setCrf(16);
Config.setPixelFormat('yuv420p');
Config.setConcurrency(8);
