// The two cuts of every film. Films are composed in "world" pixels of the 9:16 frame; the 4:5 feed cut
// shows the central 1080x1350 band of it (bandTop = 285), so key action stays inside y 285..1635.
export const FORMATS = {
  // YouTube Shorts. Overlays measured on a live Short: top ~9%, bottom ~12%, right edge from ~70% down.
  shorts: {width: 1080, height: 1920, bandTop: 0, captionY: 1330},
  // LinkedIn feed (4:5). Captions at ~77% height, above the player's controls.
  feed: {width: 1080, height: 1350, bandTop: 285, captionY: 1045},
} as const;

export type FormatId = keyof typeof FORMATS;

export const FPS = 30;

/** A y in a cut's own pixels, as a y in the 9:16 world frame. */
export const toWorldY = (format: FormatId, y: number) => y + FORMATS[format].bandTop;
