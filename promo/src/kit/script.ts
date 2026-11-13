// The shape of a film's script (src/films/<film>/script.ts) and of the voice timings the voice script writes.

export type Line = {
  id: string;
  /** What the narrator says. May hold ElevenLabs audio tags like [excited] or [whispers]. */
  text: string;
  /** Seconds of silence before the line (default 0.25). Comic timing lives here. */
  gap?: number;
};

export type FilmScript = {
  id: string;
  title: string;
  voice: {voiceId: string; model: string; settings?: Record<string, number>};
  /** Spellings that make the voice say a word right, applied only to the text sent to TTS. */
  aliases: Record<string, string>;
  lines: Line[];
  /** Seconds after the last line (end card). */
  tail: number;
  /** Sound effects by name: an ElevenLabs sound-generation prompt, its length, and how many takes to rotate. */
  sounds: Record<string, {prompt: string; seconds: number; takes?: number}>;
  music: {prompt: string};
};

export type WordTiming = {text: string; start: number; end: number};

export type VoiceLine = {file: string; duration: number; lufs?: number; words: WordTiming[]};

/** voice.json: per line, the clip (relative to public/) and its word timings in seconds. */
export type VoiceData = Record<string, VoiceLine>;

/** sounds.json: per sound name, its takes (files relative to public/). */
export type SoundData = Record<string, {file: string; lufs: number}[]>;

/** music.json: the bed (relative to public/) and its length in seconds. */
export type MusicData = {file: string; seconds: number; lufs: number};
