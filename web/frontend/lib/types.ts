export type Phase =
  | "init"
  | "genre"
  | "planning"
  | "checkpoint1"
  | "critique"
  | "checkpoint2"
  | "editing"
  | "building"
  | "validating"
  | "rating"
  | "complete";

export interface Suno {
  title?: string;
  artist?: string;
  year?: string;
  prompt?: string;
  lyrics?: string;
  tags?: string;
  cover_url?: string;
  suno_id?: string;
  disambiguated?: boolean;
}

export interface Track {
  id: string;
  display_name: string;
  bpm: number | null;
  camelot_key: string | null;
  duration_sec: number | null;
  genre: string | null;
  genre_folder?: string;
  file?: string;
  variant_of?: string | null;
  suno?: Suno;
}

export interface Catalog {
  tracks: Track[];
  genres: string[];
}

export interface StructuredProblem {
  pos_from: number;
  pos_to: number;
  key_pair: string;
  bpm_diff: number;
  text: string;
}

export interface SessionState {
  id: string;
  user_id: number;
  phase: Phase;
  genre: string | null;
  duration_min: number | null;
  mood: string | null;
  playlist: Track[];
  session_name: string | null;
  critic_verdict: string | null;
  critic_problems: string[];
  structured_problems: StructuredProblem[];
  validator_status: string | null;
  validator_issues: string[];
  created_at: string;
}

export interface User {
  id: number;
  username: string;
  email: string;
}

// WebSocket event types from server
export type ServerEvent =
  | { type: "text_delta"; content: string }
  | { type: "tool_call"; name: string; input: Record<string, unknown> }
  | { type: "tool_progress"; name: string; stage: string; message: string }
  | { type: "tool_result"; name: string; result: string }
  | { type: "phase_start"; phase: Phase }
  | { type: "phase_complete"; phase: Phase; data: unknown }
  | { type: "state"; data: SessionState }
  | { type: "error"; message: string };

// Playlists (v2.2.1)
export interface Playlist {
  id: number;
  user_id: number;
  name: string;
  created_at: string;
  updated_at: string;
  track_count: number;
}

/**
 * A playlist track row may be a full hydrated `Track` from the catalog or a
 * stub `{ id, display_name, missing: true }` if the catalog no longer
 * resolves the id (eg. it was renamed during a `--build-catalog` rebuild).
 */
export interface PlaylistTrack extends Partial<Track> {
  id: string;
  display_name: string;
  missing?: boolean;
}

export interface PlaylistDetail {
  id: number;
  user_id: number;
  name: string;
  created_at: string;
  updated_at: string;
  tracks: PlaylistTrack[];
}
