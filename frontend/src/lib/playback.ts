/** Time-indexed perception data for an uploaded clip, mirroring
 *  backend/app/perception/file_processor.py's ProcessedVideo JSON. */

export interface PlaybackBox {
  label: string;
  confidence: number;
  cx: number;   // [0, 1]
  cy: number;
  w: number;
  h: number;
}

export interface PlaybackEntity {
  id: string;
  type: "soldier" | "drone" | "poi" | "hazard" | "object";
  label?: string | null;
  x: number;     // local-frame metres
  y: number;
  z: number;
  confidence: number;
  source: string;
}

export interface PlaybackFrame {
  t: number;             // seconds from video start
  boxes: PlaybackBox[];
  entities: PlaybackEntity[];
}

export interface PlaybackData {
  name: string;
  duration_s: number;
  image_w: number;
  image_h: number;
  sample_fps: number;
  source_fps: number;
  frames: PlaybackFrame[];
  summary: {
    frame_count: number;
    detection_count: number;
    processed_at: number;
  };
}

/** Binary search: returns the most recent frame at or before `t`. The frames
 *  are recorded at sample_fps (~5 Hz), so playback at 30 fps overshoots them;
 *  we want the last frame already "passed" by the current playhead. */
export function frameAt(frames: PlaybackFrame[], t: number): PlaybackFrame | null {
  if (frames.length === 0) return null;
  let lo = 0;
  let hi = frames.length - 1;
  if (t < frames[0].t) return null;
  if (t >= frames[hi].t) return frames[hi];
  while (lo < hi) {
    const mid = (lo + hi + 1) >>> 1;
    if (frames[mid].t <= t) lo = mid;
    else hi = mid - 1;
  }
  return frames[lo];
}

/** Cumulative entity view: returns every entity seen up to and including `t`,
 *  deduped by id (most-recent wins). Useful for the Map tab so landmarks
 *  build up as the operator scrubs forward. */
export function cumulativeEntitiesAt(
  frames: PlaybackFrame[],
  t: number,
): PlaybackEntity[] {
  const out = new Map<string, PlaybackEntity>();
  for (const f of frames) {
    if (f.t > t) break;
    for (const e of f.entities) out.set(e.id, e);
  }
  return [...out.values()];
}
