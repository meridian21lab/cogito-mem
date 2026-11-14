// The mix. Every clip's loudness was measured when it was made (voice.json, sounds.json, music.json), so
// levels are set by numbers, not by ear: narration near -18 LUFS (keeping 40% of its natural range, so a
// whisper stays a whisper), effects near -21 LUFS, the bed near -22 LUFS in the gaps and 10 dB lower
// under the voice. Gains are scaled together so none exceeds 1; render.sh then masters to -14 LUFS.
import {createContext, useContext, type ReactNode} from 'react';
import {Audio, Sequence, interpolate, staticFile} from 'remotion';
import type {MusicData, SoundData, VoiceData} from './script';
import {duckedVolume} from './motion';
import type {Timeline} from './timeline';

export const LEVELS = {voice: -18, voiceRange: 0.4, sfx: -21, musicGap: -22, duck: -10};

const dbToGain = (db: number) => 10 ** (db / 20);

export type Mix = {voice: VoiceData; sounds: SoundData; music: MusicData};

type Gains = {voice: Record<string, number>; sfx: Record<string, number[]>; musicDb: number};

export const mixGains = ({voice, sounds, music}: Mix): Gains => {
  const vl = Object.entries(voice).map(([id, v]) => [id, v.lufs ?? LEVELS.voice] as const);
  const mean = vl.reduce((s, [, l]) => s + l, 0) / Math.max(1, vl.length);
  const raw = {
    voice: Object.fromEntries(vl.map(([id, l]) => [id, LEVELS.voice + LEVELS.voiceRange * (l - mean) - l])),
    sfx: Object.fromEntries(Object.entries(sounds).map(([k, takes]) => [k, takes.map((t) => LEVELS.sfx - t.lufs)])),
    music: LEVELS.musicGap - music.lufs,
  };
  const all = [...Object.values(raw.voice), ...Object.values(raw.sfx).flat(), raw.music];
  const headroom = Math.min(0, -Math.max(...all)); // dB to pull everything down so the loudest gain is 1
  return {
    voice: Object.fromEntries(Object.entries(raw.voice).map(([k, d]) => [k, dbToGain(d + headroom)])),
    sfx: Object.fromEntries(Object.entries(raw.sfx).map(([k, ds]) => [k, ds.map((d) => dbToGain(d + headroom))])),
    musicDb: raw.music + headroom,
  };
};

const Ctx = createContext<{mix: Mix; gains: Gains} | null>(null);

export const SoundProvider = ({mix, children}: {mix: Mix; children: ReactNode}) => <Ctx.Provider value={{mix, gains: mixGains(mix)}}>{children}</Ctx.Provider>;

const useMix = () => {
  const m = useContext(Ctx);
  if (!m) throw new Error('Sound components need a <SoundProvider>');
  return m;
};

/** 30 ms (one frame) fades at both ends of a clip, so nothing clicks. */
const edgeFade = (f: number, len: number) => Math.min(1, f + 0.001, Math.max(0, len - f));

export const Voice = ({tl}: {tl: Timeline}) => {
  const {gains} = useMix();
  return (
    <>
      {tl.lines.map((l) => (
        <Sequence key={l.id} from={l.from} durationInFrames={l.to - l.from + 6} name={`voice ${l.id}`}>
          <Audio src={staticFile(l.file)} volume={gains.voice[l.id] ?? 1} />
        </Sequence>
      ))}
    </>
  );
};

/** A sound effect at frame `at`. `take` picks a rotation take (default by position); `db` trims it. */
export const Sfx = ({name, at, take, db = 0, frames = 60}: {name: string; at: number; take?: number; db?: number; frames?: number}) => {
  const {mix, gains} = useMix();
  const takes = mix.sounds[name];
  if (!takes) throw new Error(`No sound "${name}" in sounds.json: add it to the script and run npm run sfx`);
  const i = (take ?? Math.abs(Math.round(at / 7))) % takes.length;
  const g = gains.sfx[name][i] * dbToGain(db);
  return (
    <Sequence from={at} durationInFrames={frames} name={`sfx ${name}`}>
      <Audio src={staticFile(takes[i].file)} volume={(f) => g * edgeFade(f, frames)} />
    </Sequence>
  );
};

/** The bed: ducked under the voice, faded in at the start and out by `fadeOutTo`. */
export const Music = ({tl, fadeOutFrom, fadeOutTo}: {tl: Timeline; fadeOutFrom: number; fadeOutTo: number}) => {
  const {mix, gains} = useMix();
  return (
    <Audio
      src={staticFile(mix.music.file)}
      volume={(f) =>
        duckedVolume(f, tl, {base: gains.musicDb, duck: LEVELS.duck, attack: 5, release: 14}) *
        interpolate(f, [0, 8], [0, 1], {extrapolateRight: 'clamp'}) *
        interpolate(f, [fadeOutFrom, fadeOutTo], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})
      }
    />
  );
};
