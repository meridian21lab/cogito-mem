// npm run music -- <film>: the music bed, generated to the film's length (needs voice.json first).
// Writes public/films/<film>/music/bed-<hash>.mp3 and music.json.
import {existsSync} from 'node:fs';
import {join, relative} from 'node:path';
import {FPS} from '../src/kit/formats';
import type {MusicData, VoiceData} from '../src/kit/script';
import {buildTimeline} from '../src/kit/timeline';
import {audioSeconds, loudness} from './lib/audio';
import {PUBLIC, cacheKey, filmDir, loadFilm, post, readJson, run, writeAtomic} from './lib/eleven';

run(async () => {
  const script = await loadFilm(process.argv[2]);
  const voice = readJson<VoiceData | null>(join(filmDir(script.id), 'voice.json'), null);
  if (!voice) throw new Error(`No voice.json yet: run npm run voice -- ${script.id} first`);
  const seconds = Math.ceil(buildTimeline(script, voice, FPS).total / FPS) + 1;
  const key = cacheKey({prompt: script.music.prompt, seconds});
  const mp3 = join(filmDir(script.id), 'music', `bed-${key}.mp3`);
  if (existsSync(mp3)) console.log('music: cached');
  else {
    const res = await post('/v1/music?output_format=mp3_44100_128', {prompt: script.music.prompt, music_length_ms: seconds * 1000, force_instrumental: true});
    writeAtomic(mp3, Buffer.from(await res.arrayBuffer()));
    console.log(`music: generated (${seconds} s)`);
  }
  const out: MusicData = {file: relative(PUBLIC, mp3), seconds: audioSeconds(mp3), lufs: loudness(mp3).lufs};
  writeAtomic(join(filmDir(script.id), 'music.json'), JSON.stringify(out, null, 1));
});
