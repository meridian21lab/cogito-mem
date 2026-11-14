// npm run check -- <film>: the automatic checks on the final cuts in out/<film>/ before the author sees them.
// Fails (exit 1) on: loudness off -14 LUFS by more than 1 LU, true peak above -1 dBTP, a still stretch over
// 3 s, or a length outside 25-60 s.
import {spawnSync} from 'node:child_process';
import {existsSync} from 'node:fs';
import {join} from 'node:path';
import {audioSeconds} from './lib/audio';
import {PROMO, run} from './lib/eleven';
import {stillRuns} from './lib/still';

const SAMPLE_FPS = 10;
const W = 54;
const H = 96;

const truePeakAndLufs = (file: string) => {
  const r = spawnSync('ffmpeg', ['-hide_banner', '-nostats', '-i', file, '-af', 'ebur128=peak=true', '-f', 'null', '-'], {encoding: 'utf8'});
  const s = r.stderr.slice(r.stderr.lastIndexOf('Summary:'));
  return {lufs: Number(/I:\s+(-?[\d.]+) LUFS/.exec(s)?.[1]), peak: Number(/True peak:\s+Peak:\s+(-?[\d.]+) dBFS/.exec(s)?.[1])};
};

const frameDiffs = (file: string) => {
  const r = spawnSync('ffmpeg', ['-v', 'error', '-i', file, '-vf', `fps=${SAMPLE_FPS},scale=${W}:${H},format=gray`, '-f', 'rawvideo', '-'], {maxBuffer: 1 << 28});
  const buf = r.stdout as Buffer;
  const n = Math.floor(buf.length / (W * H));
  const diffs = [99];
  for (let f = 1; f < n; f++) {
    let sum = 0;
    for (let i = 0; i < W * H; i++) sum += Math.abs(buf[f * W * H + i] - buf[(f - 1) * W * H + i]);
    diffs.push(sum / (W * H));
  }
  return diffs;
};

run(async () => {
  const film = process.argv[2];
  if (!film) throw new Error('usage: npm run check -- <film>');
  let failed = false;
  for (const cut of ['shorts', 'feed']) {
    const file = join(PROMO, 'out', film, `${cut}.mp4`);
    if (!existsSync(file)) throw new Error(`No ${file}: run bash scripts/render.sh ${film}`);
    const seconds = audioSeconds(file);
    const {lufs, peak} = truePeakAndLufs(file);
    const still = stillRuns(frameDiffs(file), SAMPLE_FPS, 0.35);
    const problems = [
      Math.abs(lufs + 14) > 1 && `loudness ${lufs} LUFS (want -14 ± 1)`,
      peak > -1 && `true peak ${peak} dBTP (want ≤ -1)`,
      (seconds < 25 || seconds > 60) && `length ${seconds.toFixed(1)} s (want 25-60)`,
      ...still.map((r) => `still for ${r.seconds.toFixed(1)} s from ${r.from.toFixed(1)} s`),
    ].filter(Boolean);
    console.log(`${cut}: ${seconds.toFixed(1)} s, ${lufs} LUFS, true peak ${peak} dBTP${problems.length ? `\n  FAIL ${problems.join('\n  FAIL ')}` : ', OK'}`);
    failed ||= problems.length > 0;
  }
  if (failed) process.exit(1);
});
