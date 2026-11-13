// npm run sfx -- <film>: every sound effect in the script, each take cached by content hash.
// Writes public/films/<film>/sfx/<name>-<take>-<hash>.mp3 and sounds.json.
import {existsSync} from 'node:fs';
import {join, relative} from 'node:path';
import type {SoundData} from '../src/kit/script';
import {PUBLIC, cacheKey, filmDir, loadFilm, post, run, writeAtomic} from './lib/eleven';

run(async () => {
  const script = await loadFilm(process.argv[2]);
  const out: SoundData = {};
  for (const [name, s] of Object.entries(script.sounds)) {
    out[name] = [];
    for (let take = 1; take <= (s.takes ?? 1); take++) {
      const key = cacheKey({prompt: s.prompt, seconds: s.seconds, take});
      const mp3 = join(filmDir(script.id), 'sfx', `${name}-${take}-${key}.mp3`);
      if (existsSync(mp3)) console.log(`${name} #${take}: cached`);
      else {
        const res = await post('/v1/sound-generation?output_format=mp3_44100_192', {text: s.prompt, duration_seconds: s.seconds, prompt_influence: 0.6});
        writeAtomic(mp3, Buffer.from(await res.arrayBuffer()));
        console.log(`${name} #${take}: generated`);
      }
      out[name].push(relative(PUBLIC, mp3));
    }
  }
  writeAtomic(join(filmDir(script.id), 'sounds.json'), JSON.stringify(out, null, 1));
  console.log(`sounds.json: ${Object.keys(out).length} sounds`);
});
