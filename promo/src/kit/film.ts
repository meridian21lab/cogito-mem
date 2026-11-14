// Loading a film's generated audio data for its compositions: voice.json, sounds.json and music.json
// from public/films/<film>/, and the film's length from the timeline.
import {staticFile, type CalculateMetadataFunction} from 'remotion';
import {FPS, type FormatId} from './formats';
import type {FilmScript, MusicData, SoundData, VoiceData} from './script';
import type {Mix} from './Sound';
import {buildTimeline} from './timeline';

const get = async <T,>(path: string): Promise<T | null> => {
  const r = await fetch(staticFile(path));
  return r.ok ? ((await r.json()) as T) : null;
};

export const loadMix = async (film: string): Promise<Mix | null> => {
  const [voice, sounds, music] = await Promise.all([
    get<VoiceData>(`films/${film}/voice.json`),
    get<SoundData>(`films/${film}/sounds.json`),
    get<MusicData>(`films/${film}/music.json`),
  ]);
  return voice && sounds && music ? {voice, sounds, music} : null;
};

/** calculateMetadata for a film: loads its mix and sets the duration from the narration. */
export const filmMetadata =
  (script: FilmScript): CalculateMetadataFunction<{format: FormatId; mix: Mix | null}> =>
  async ({props}) => {
    const mix = await loadMix(script.id);
    const durationInFrames = mix ? buildTimeline(script, mix.voice, FPS).total : FPS;
    return {durationInFrames, props: {...props, mix}};
  };
