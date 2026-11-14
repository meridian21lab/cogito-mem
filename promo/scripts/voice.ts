// npm run voice -- <film>: narration for every line, with word timings, cached by content hash.
// Writes public/films/<film>/voice/<line>-<hash>.mp3 (+ .json alignment) and voice.json for the timeline.
import {existsSync, readFileSync} from 'node:fs';
import {join, relative} from 'node:path';
import type {VoiceData} from '../src/kit/script';
import {alignmentToWords, captionWords, ttsText} from '../src/kit/words';
import {audioSeconds, loudness} from './lib/audio';
import {PUBLIC, cacheKey, filmDir, loadFilm, post, run, writeAtomic} from './lib/eleven';

type Alignment = {characters: string[]; character_start_times_seconds: number[]; character_end_times_seconds: number[]};

run(async () => {
  const film = process.argv[2];
  const script = await loadFilm(film);
  const {voiceId, model, settings} = script.voice;
  const out: VoiceData = {};
  for (const line of script.lines) {
    const text = ttsText(line.text, script.aliases);
    const key = cacheKey({text, voiceId, model, settings: settings ?? {}});
    const mp3 = join(filmDir(script.id), 'voice', `${line.id}-${key}.mp3`);
    const meta = mp3.replace(/\.mp3$/, '.json');
    let alignment: Alignment;
    if (existsSync(mp3) && existsSync(meta)) {
      alignment = JSON.parse(readFileSync(meta, 'utf8'));
      console.log(`${line.id}: cached`);
    } else {
      const res = await post(`/v1/text-to-speech/${voiceId}/with-timestamps?output_format=mp3_44100_128`, {
        text,
        model_id: model,
        ...(settings ? {voice_settings: settings} : {}),
      });
      const body = (await res.json()) as {audio_base64: string; alignment: Alignment};
      alignment = body.alignment;
      writeAtomic(meta, JSON.stringify(alignment));
      writeAtomic(mp3, Buffer.from(body.audio_base64, 'base64'));
      console.log(`${line.id}: generated (${text.length} chars)`);
    }
    const words = alignmentToWords(alignment.characters, alignment.character_start_times_seconds, alignment.character_end_times_seconds);
    const shown = captionWords(line.text);
    if (words.length !== shown.length) {
      throw new Error(`${line.id}: the voice says ${words.length} words but captions show ${shown.length}.\n  spoken: ${words.map((w) => w.text).join(' ')}\n  shown:  ${shown.join(' ')}`);
    }
    out[line.id] = {file: relative(PUBLIC, mp3), duration: audioSeconds(mp3), lufs: loudness(mp3).lufs, words};
  }
  writeAtomic(join(filmDir(script.id), 'voice.json'), JSON.stringify(out, null, 1));
  const total = Object.values(out).reduce((s, l) => s + l.duration, 0);
  console.log(`voice.json: ${script.lines.length} lines, ${total.toFixed(1)} s of narration`);
});
