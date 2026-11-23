// Shapes the Studio backend actually returns. Keep these honest: a field that
// the API does not send must not appear here.

export interface Project {
  id: string;
  name: string;
  brand: string;
  workflow_name: string;
  status: string;
  current_step?: string | null;
  history?: StepRecord[];
  steps_history?: unknown[];
  assets?: Record<string, string>;
  created_at?: string;
  metadata?: Record<string, unknown>;
}

export interface StepRecord {
  step_name?: string;
  agent_name?: string;
  status?: string;
  timestamp?: string;
  started_at?: string;
  completed_at?: string;
  error?: string;
  [key: string]: unknown;
}

// One step of a workflow definition, as GET /api/workflows sends it.
export interface WorkflowStepInfo {
  name: string;
  agent_role: string;
  description?: string;
  requires_approval?: boolean;
}

export interface WorkflowInfo {
  id?: string;
  name: string;
  description?: string;
  steps?: WorkflowStepInfo[];
}

export interface Topic {
  id?: string;
  topic: string;
  category?: string;
  channel?: string;
  viral_potential?: number;
  country?: string;
  source_type?: string;
  sources_used?: string[] | string;
  visual_requirements?: string[] | string;
  exclusion_audit?: string;
  notes?: string;
  saved_at?: string;
  stage?: string;
  added_by?: string;
  tags?: string[];
  updated_at?: string;
  // The medium picked for this story (real / explainer / stick_figure /
  // cartoon); carried into the project when it is started.
  art_style?: string | null;
  rank?: number;
  scores?: { potential?: number; virality?: number };
  // Audience Desk rows (source_type 'viewer_requests'): the comments behind it.
  evidence?: AudienceEvidence;
}

export interface AudienceVideo {
  id: string;
  title?: string;
  channel?: string;
  views?: number;
  duration?: number;
  source?: 'own' | 'competitor' | 'search' | string;
  comments_read?: number;
  comment_count?: number;
}

export interface AudienceEvidence {
  kind?: string;
  mentions?: number;
  likes?: number;
  score?: number;
  quotes?: string[];
  videos?: AudienceVideo[];
  found_at?: string;
}

// One thing the viewers asked for, from the Audience Desk's last run.
export interface AudienceFinding {
  topic: string;
  kind: string;
  kind_label?: string;
  in_niche?: boolean;
  why?: string;
  mentions: number;
  likes: number;
  score: number;
  quotes: string[];
  videos: AudienceVideo[];
  comment_ids?: number[];
  saved_topic_id?: string;
}

export interface AudienceRun {
  brand: string;
  ran_at?: string;
  seconds?: number;
  videos: AudienceVideo[];
  comments_read: number;
  findings: AudienceFinding[];
}

export interface AudienceSources {
  brand: string;
  own: string[];
  queries: string[];
  competitors: { url: string; name?: string; source?: 'auto' | 'manual'; reason?: string; channel_id?: string }[];
  default_queries: string[];
}

export interface AudienceSettings {
  enabled: boolean;
  max_videos: number;
  per_video: number;
  auto_save_top: number;
  last_run: string;
  last?: {
    ran_at?: string;
    done?: { brand: string; videos: number; comments: number; findings: number; seconds: number }[];
    saved?: { brand: string; topic: string; mentions: number; id: string }[];
    failed?: { brand: string; error: string }[];
  } | null;
}

// One `[INVOKE_AGENT: X]` block the strategist emitted and the Studio ran
// (roadmap v9, B1). `skipped` means it was over the per-reply cap.
export interface Invocation {
  agent: string;
  task: string;
  output: string;
  simulated?: boolean;
  skipped?: boolean;
  error?: string;
}

// One thing a Studio Assistant turn did (2026-10-22): the strategist writing,
// a delegated specialist, a web lookup, a vault save, a studio tool. Served
// live by GET /api/studio/chat_progress/{turn_id} while the turn runs and
// returned with the reply once it is over.
export interface ProgressStep {
  index: number;
  kind: string;
  label: string;
  detail?: string;
  status: 'running' | 'done' | 'failed' | 'skipped' | string;
  seconds?: number | null;
  note?: string;
}

export interface TurnProgress {
  turn_id: string;
  agent: string;
  channel: string;
  status: 'running' | 'done' | 'failed' | string;
  elapsed: number;
  note?: string;
  steps: ProgressStep[];
}

export interface ChatMessage {
  sender: 'user' | 'agent';
  text: string;
  timestamp: string;
  simulated?: boolean;
  error?: boolean;
  // Which persona actually answered this turn - the picker can change between
  // turns, so the header cannot use the currently selected one.
  agent?: string;
  invocations?: Invocation[];
  progress?: ProgressStep[];
  elapsed?: number;
  // The message a failed turn was answering, so a Retry can send it again.
  retryText?: string;
}

export interface StudioSettings {
  selected_provider?: string;
  gemini_model?: string;
  gemini_api_key_set?: boolean;
  openai_api_key_set?: boolean;
  claude_api_key_set?: boolean;
  claude_url?: string;
  claude_model?: string;
  produce_llm_provider?: string;
  thinking_agents?: boolean;
  thinking_production?: boolean;
  pixabay_api_key_set?: boolean;
  pixabay_enabled?: boolean;
  lm_studio_url?: string;
  lm_studio_model?: string;
  [key: string]: unknown;
}

// One row of GET /api/agents. Everything but `name` comes from the persona
// file's frontmatter, so a field the file omits arrives empty, never invented.
export interface AgentInfo {
  name: string;
  department?: string;
  role?: string;
  inputs?: string[];
  outputs?: string[];
  dependencies?: string[];
  version?: string;
  status?: string;
  file?: string;
}

export interface ModelStatus {
  provider: string;
  configured_model: string;
  connected: boolean;
  loaded: boolean;
  active_model?: string;
  loaded_models?: string[];
  message?: string;
}

export interface HealthInfo {
  status: string;
  app?: string;
  version?: string;
  port?: number;
  pid?: number;
  model_status?: ModelStatus;
}

export type ToastKind = 'success' | 'error' | 'info';

export interface ToastItem {
  id: string;
  kind: ToastKind;
  text: string;
}

export type TabId =
  | 'studio_chat'
  | 'dashboard'
  | 'projects'
  | 'topic_vault'
  | 'audience'
  | 'story_desk'
  | 'board'
  | 'analyze'
  | 'research'
  | 'music'
  | 'writing_style'
  | 'scheduler_desk'
  | 'bulk_edit'
  | 'agent_creator_studio'
  | 'agents_group_chat'
  | 'ai_workforce'
  | 'departments'
  | 'health'
  | 'settings'
  | 'logs';

export interface LogEntry {
  timestamp: string;
  level: string;
  logger: string;
  message: string;
  source: string;
  traceback: string[];
}

export interface LogsResponse {
  status: string;
  total_parsed: number;
  error_count: number;
  warning_count: number;
  returned: number;
  level_filter: string;
  logs: LogEntry[];
}

// One result row from GET /api/research/sources (Feature A: public archives,
// books, and newspaper search).
export interface SourceItem {
  title: string;
  snippet?: string;
  url: string;
  source: string;
  kind: 'book' | 'archive' | 'news' | string;
}

export interface DeepResearchResult {
  query: string;
  results: SourceItem[];
  by_kind?: { news?: SourceItem[]; archives?: SourceItem[]; books?: SourceItem[] };
  sources_searched?: Array<{ source: string; count: number }>;
}

// Video intelligence (v6). The analysis object is model output and is read
// defensively in the page; only the stable fields are typed.
export interface VideoIntelSummary {
  id: string;
  kind: 'video' | 'channel';
  title?: string;
  channel?: string;
  thumbnail?: string;
  view_count?: number;
  outlier_multiple?: number | null;
  channel_for?: string;
  simulated?: boolean;
  generated_at?: string;
}

// The production queue (GET /api/produce/queue, app/services/produce_queue.py):
// every produce_video run, any channel, one at a time.
export type ProduceQueueResumePoint = 'start' | 'transcribe' | 'plan' | 'finalize' | 'render';

export interface ProduceQueueStageTime {
  stage: ProduceQueueResumePoint;
  started_at: string;
  finished_at: string | null;
  seconds: number | null;
  outcome: 'done' | 'paused' | 'cancelled' | 'failed' | 'awaiting_review' | 'interrupted' | null;
}

export interface ProduceQueueItem {
  id: string;
  project_id: string;
  brand: string;
  title: string;
  recording_path: string;
  mode: string;
  precut: boolean;
  status: 'queued' | 'running' | 'paused' | 'awaiting_review' | 'done' | 'failed' | 'cancelled';
  // Where a resume/retry picks up, and the last safe point the run reached.
  resume_from: ProduceQueueResumePoint;
  checkpoint: ProduceQueueResumePoint | null;
  pause_requested: boolean;
  cancel_requested: boolean;
  attempts: number;
  error: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  // One entry per stage per attempt; the open one (finished_at null) is running.
  // Queue waits and review gates are not counted.
  stage_times?: ProduceQueueStageTime[];
  // Live, from the project's produce_video status (running / awaiting items).
  message?: string | null;
  progress?: number | null;
  stage_state?: string | null;
  // Done items: the finished video, when it is still on disk.
  final_output_path?: string | null;
}

export interface ProduceQueue {
  paused: boolean;
  worker_active: boolean;
  items: ProduceQueueItem[];
}

// GET /api/projects/{id}/produce_video/status (app/api/produce_api.py). The
// fine-grained progress is an in-memory dict; the queue item (persisted)
// rides along as `queue_item` while the project has one unfinished.
export interface ProduceVideoStatus {
  state: 'idle' | 'queued' | 'paused' | 'starting' | 'running' | 'ready' | 'failed'
    // Paused at a review gate (`review_mode`, app/api/produce_api.py) --
    // resume with POST .../produce_video/continue, or drop it with .../cancel.
    | 'awaiting_cut_review' | 'awaiting_plan_review' | 'awaiting_effects_review' | 'cancelled';
  queue_item?: ProduceQueueItem;
  // The ~20 s effects sample BuzzEdit rendered for an `awaiting_effects_review`
  // gate (video_settings.effects_review): its URL, what went into it, and
  // whether a re-test is rendering right now.
  effects_sample?: EffectsSample | null;
  sample_running?: boolean;
  sample_error?: string | null;
  sample_progress?: number | null;
  message?: string;
  progress?: number | null;
  error?: string | null;
  warning?: string | null;
  buzzedit_job_id?: string;
  output_path?: string | null;
  // The finished video where the creator works (next to the recording by
  // default); `output_path` is the file BuzzEdit rendered.
  final_output_path?: string | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  report?: Record<string, any> | null;
  // How the recording differed from the written script
  // (integrations/script_reconcile.py); present once the match has run.
  deviation?: {
    script_spoken_share: number;
    adlib_share: number;
    beats_placed: number;
    beats_dropped: number;
    skipped_paragraphs: number;
  };
  // Per-window visual-planning stats (integrations/visual_windows.py),
  // present once planning against the CUT take has run.
  planning?: {
    windows: number;
    ok: number;
    failed: Array<{ window_index: number; reason: string }>;
  } | null;
  // The gate stage a `awaiting_*` state is sitting at -- pass this back as
  // `stage` to POST .../produce_video/continue.
  stage?: 'cut_review' | 'plan_review' | 'effects_review';
  // True when this status was reconstructed from `project.metadata` because
  // the backend restarted since the run paused (no in-memory status left).
  resumed_after_restart?: boolean;
}

// A planned visual beat, index-anchored by the model then resolved to a
// verbatim quote/timestamp (integrations/visual_windows.py::parse_window_beats),
// as stored in production/visual_plan_take.json and reviewed in the Studio.
export interface VisualPlanBeat {
  kind: string;
  anchor: string;
  start?: number;
  end?: number;
  window_index?: number;
  // The single editable "what to generate" string (visual_windows.prompt_text_for);
  // edit this and send the beat back as-is on continue.
  prompt?: string;
  deleted?: boolean;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  [key: string]: any;
}

export interface VisualPlanTake {
  beats: VisualPlanBeat[];
  planning?: {
    windows: number;
    ok: number;
    failed: Array<{ window_index: number; reason: string }>;
  };
}

// backend/integrations/buzzedit_settings.py::GENRES / DENSITIES / VOICE_PRESETS.
export const GENRES = [
  'general', 'horror', 'true_crime', 'comedy', 'gaming', 'tech', 'science_education',
  'finance', 'motivational', 'health_fitness', 'cooking', 'travel', 'devotional',
  'news', 'vlog', 'documentary', 'mystery', 'geopolitics',
] as const;
export type Genre = (typeof GENRES)[number];

export const DENSITIES = ['calm', 'balanced', 'busy', 'max'] as const;
export type Density = (typeof DENSITIES)[number];

export const VOICE_PRESETS = [
  'studio_mic', 'broadcast', 'warm_radio', 'rap_vocal', 'crisp_bass', 'horror_intimate', 'clean', 'podcast', 'light',
] as const;
export type VoicePreset = (typeof VOICE_PRESETS)[number];

// One brand's saved genre/density/voice-preset defaults
// (GET/PUT /api/channel_profiles, app/api/produce_api.py).
export interface ChannelProfile {
  genre: string;
  genre_secondary?: string | null;
  density: string;
  voice_preset?: string;
  // The medium of the pictures: real / explainer / stick_figure / cartoon.
  art_style?: string | null;
}

export interface ChannelProfilesResponse {
  profiles: Record<string, ChannelProfile>;
  genres: string[];
  densities: string[];
  art_styles?: string[];
  art_style_labels?: Record<string, string>;
}

// A project's style overrides and the fully resolved settings BuzzEdit will
// actually render with (GET/PUT /api/projects/{id}/video_settings).
export interface VideoSettings {
  // "story": pictures and videos only (no captions, cards, sfx); "full": everything.
  visual_style?: "full" | "story";
  // The medium of the pictures, clips, thumbnail and text cards:
  // real / explainer / stick_figure / cartoon (null = the channel's own).
  art_style?: string | null;
  genre?: string;
  genre_secondary?: string | null;
  density?: string;
  voice_preset?: string;
  precut?: boolean;
  allow_free_stock?: boolean;
  target_coverage?: number;
  video_broll_share?: number;
  // Share of the running time that is still images (video_broll_share then
  // means the clips' share of the running time; the face gets the rest).
  image_broll_share?: number;
  broll_seconds_min?: number;
  broll_seconds_max?: number;
  min_oncamera_gap_s?: number;
  zoom_depth?: number;
  base_zoom?: number;
  punch_rate_per_minute?: number;
  text_fx_per_minute?: number;
  // "none": render straight through. "plan" (default): pause after visual
  // planning so the creator can review/edit the beats before the render.
  // "cuts_and_plan": also pause right after the auto-cut, to review BuzzEdit's
  // cuts before anything is planned against them.
  review_mode?: 'none' | 'plan' | 'cuts_and_plan';
  // Pause just before the render on a ~20 s effects sample of the real cut.
  effects_review?: boolean;
  // Background music: off entirely, one brief for the whole video (BuzzEdit's
  // cue grammar), follow the script's [music: ...] cues, and the engine.
  music?: boolean;
  music_brief?: string;
  music_cues?: boolean;
  music_engine?: 'ace_step' | 'stable_audio';
  // Library tracks the creator picked, each at a fixed level; they replace the
  // automatic music. Played layered ("together") or in turn ("sequence").
  music_tracks?: { file: string; volume_db: number; duck: boolean }[] | null;
  music_tracks_mode?: 'together' | 'sequence';
  // How the creator's face is used: "mixed" (between the pictures all
  // through, the mix sliders) or "face_intro" (only his face for the first
  // face_intro_seconds, then pictures and clips only).
  face_layout?: 'mixed' | 'face_intro' | null;
  face_intro_seconds?: number | null;
  // BuzzEdit motion graphics: off = every animated effect as its still card;
  // parallax_share = share of stills given the 2.5D depth move (default 0.3).
  motion_graphics?: boolean | null;
  parallax_share?: number | null;
}

// Recording sessions (backend app/services/session_format.py): the Shorts are
// recorded first, then the long video; the recording is split at the greeting.
export interface ChannelFormatDefaults {
  shorts_first: boolean;
  shorts_count: number;
  face_layout: 'mixed' | 'face_intro';
  face_intro_seconds: number;
}

export interface ChannelFormatsState {
  channels: Record<string, ChannelFormatDefaults>;
  episode_formats: Record<string, { key: string; label: string }[]>;
  next_format: Record<string, string | null>;
  pinned_format: Record<string, string | null>;
  locked_format?: Record<string, string | null>;
}

export interface SessionSplitShort {
  index: number;
  title: string;
  from_s: number;
  to_s: number;
  clip: string;
  project_id: string | null;
  queued?: boolean;
  error?: string;
  matched_script?: boolean;
}

export interface SessionSplit {
  buzzedit_project_id: string;
  boundary_s: number;
  how: 'greeting' | 'manual';
  shorts: SessionSplitShort[];
  warning: string | null;
  programme_cut_s?: number;
}

export interface SessionParent {
  project_id: string;
  name: string;
  index: number;
  count: number;
  from_s: number;
  to_s: number;
}

export interface EffectsSample {
  url: string | null;
  rendered_at?: number;
  result?: {
    window?: [number, number];
    text_fx?: Record<string, number>;
    zooms?: number;
    sfx?: number;
    music?: string;
    person_matte?: string;
    skipped?: Array<{ style?: string; reason?: string }>;
  };
}

export const REVIEW_MODES = ['none', 'plan', 'cuts_and_plan'] as const;
export type ReviewMode = (typeof REVIEW_MODES)[number];

export interface VideoSettingsResponse {
  video_settings: VideoSettings;
  // Set when the change was also handed to a BuzzEdit render in progress
  // (the mid-production change): the live subset BuzzEdit now follows.
  live_applied?: Record<string, number> | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  effective: Record<string, any>;
  // Which resolution layer ("base" | "channel_profile" | "project" | "request")
  // each effective field came from.
  sources: Record<string, string>;
  // Video / images / face as shares of the running time (the three sliders).
  mix?: { video: number; images: number; face: number; mode: 'runtime' | 'coverage' };
}

// POST /api/topics/validate (Feature 2: topic demand validation). `verdict`
// is model output parsed from an LLM response, so every field beyond the
// envelope is optional and must be read defensively.
export interface TopicValidation {
  topic: string;
  channel?: string;
  simulated?: boolean;
  generated_at?: string;
  steps?: Array<{ step?: number; source?: string; detail?: string; count?: number; status?: string }>;
  evidence?: {
    youtube?: Array<{
      title?: string;
      url?: string;
      view_count?: number;
      duration?: number;
      channel?: string;
      upload_date?: string;
    }>;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    youtube_stats?: Record<string, any>;
    web?: Array<{ title?: string; snippet?: string; url?: string; source?: string }>;
    trends?: {
      available?: boolean;
      avg?: number;
      latest?: number;
      trend?: string;
      note?: string;
    };
  };
  verdict?: {
    demand?: { score?: number; reason?: string };
    competition?: { level?: string; saturation?: string; note?: string };
    differentiation?: { angle?: string; gap?: string };
    audience_fit?: string;
    recommendation?: 'make' | 'refine' | 'skip' | string;
    confidence?: number;
    reasons?: string[];
    suggested_title?: string;
    risks?: string[];
    top_competitors?: Array<{ title?: string; views?: number; url?: string }>;
    alternatives?: Array<{ topic?: string; why?: string }>;
  };
}

export interface VideoIntel {
  kind: 'video' | 'channel';
  id: string;
  channel_for: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  video: Record<string, any>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  metrics: Record<string, any>;
  recent: Array<{ id: string; title: string; view_count: number; duration: number; url?: string; outlier_multiple?: number | null }>;
  transcript_excerpt?: Array<{ t: number; text: string }>;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  analysis: Record<string, any>;
  simulated: boolean;
  generated_at: string;
}

// BuzzEdit's sound-effects library (GET/PUT /api/produce/sfx/library, POST
// .../refresh): the folders searched for the scene sounds the agents cue --
// folder names are the tags. `buzzedit: null` means BuzzEdit is offline.
export interface SfxLibrarySummary {
  dirs: string[];
  default: string[];
  roots: string[];
  count: number;
  effects: number;
  beds: number;
  music: number;
  tags: { tag: string; count: number }[];
  missing: string[];
  indexed_at: string;
}

export interface SfxLibraryResponse {
  dirs: string[];
  default: string[];
  buzzedit: SfxLibrarySummary | null;
}

// A Stable Audio Open render for one missing effect or background bed
// (POST /api/produce/sfx/generate, GET /api/produce/sfx/jobs/{job_id}).
export interface SfxJob {
  job_id: string;
  state: 'queued' | 'running' | 'done' | 'failed';
  stage?: string;
  text: string;
  kind: 'accent' | 'bed';
  seconds: number;
  path: string | null;
  duration_s: number | null;
  error: string | null;
}

// Auto Story (AUTO_STORY_PLAN.md §3.3, §3.6): videos made end to end in the
// creator's voice -- /api/auto_story/*.
export interface AutoStoryFormat {
  key: string;
  label: string;
  // A mood reel's own pickers (REELS_DESK_PLAN.md §6): no face, no voice.
  lengths?: string[];
  styles?: string[];
  themes?: { key: string; label: string }[];
}

export interface AutoStorySettings {
  enabled: boolean;
  per_channel: Record<string, number>;
  formats: Record<string, string[]>;
  publish: boolean;
  voice: string;
  last_run: string;
  last: Record<string, unknown> | null;
  face_intro_clips: Record<string, string>;
  voice_style?: Record<string, VoiceStyle>;
}

// Voice and delivery (VOICE_DELIVERY_PLAN.md S1/S2): per-channel mood,
// pacing and dramatic-moments settings, sent as `style` with every
// auto-story narration -- /api/auto_story/moods, /api/auto_story/voice_preview.
export interface VoiceStyle {
  mood?: string;
  pace?: number;
  word_gap_ms?: number;
  phrase_pause_s?: number;
  sentence_pause_s?: number;
  exaggeration?: number;
  temperature?: number;
  cfg_weight?: number;
  dramatic?: 'off' | 'subtle' | 'strong';
}

export interface VoiceMood {
  id: string;
  label: string;
  description?: string;
  style: Record<string, number>;
}

export interface NarrationJobStatus {
  job_id: string;
  state: 'running' | 'done' | 'failed' | string;
  message?: string;
  result?: { wav?: string; seconds?: number; duration_s?: number } | null;
}

// Ask before publishing (STUDIO_DIRECTOR_PLAN.md; Fable review #10 /
// enhancement 3): every record that reaches a publishable state defaults to
// "needs_review" -- the schedulers and the YouTube auto-publish path wait
// for "approved"; a "rejected" one carries why.
export interface AutoStoryReview {
  state: 'needs_review' | 'approved' | 'rejected' | string;
  at?: string;
  reason?: string | null;
}

export interface AutoStoryRecord {
  project_id: string;
  name: string;
  brand: string;
  format: string;
  state: string;
  started_at: string;
  final: string | null;
  posted: {
    youtube?: string | { skipped?: string; url?: string; error?: string };
    instagram?: string | { skipped?: string; url?: string; error?: string; permalink?: string; media_id?: string; at?: string };
  };
  package_dir?: string | null;
  error?: string | null;
  review?: AutoStoryReview | null;
  cover?: string | null;
  caption?: string | null;
  archived?: boolean;
}

// Instagram Reels publishing (integrations/instagram_publish.py), REELS_DESK_PLAN.md R7.
// Settings are named accounts, not one slot per channel: a channel can post
// to more than one account (Life3Baje's mood reels go to a separate account,
// @khayal3bajefeels, from its ordinary reels), routed by a
// {"channel": "account", "channel/format": "account"} table where the
// format-specific route wins.
export interface InstagramAccountSettings {
  ig_user_id: string;
  username: string;
  access_token_set: boolean;
  app_id: string;
  app_secret_set: boolean;
  token_expires_at: number | null;
  enabled: boolean;
  post_times: string[];
  caption_suffix: string;
}

export interface InstagramSettingsResponse {
  channels: string[];
  accounts: Record<string, InstagramAccountSettings>;
  routes: Record<string, string>;
}

export interface InstagramDiscoveredAccount {
  page_id: string;
  page_name: string;
  ig_user_id: string;
  username: string;
  access_token: string;
}

export interface InstagramAccountStatus {
  connected: boolean;
  username: string;
  token_days_left: number | null;
  token_expired: boolean;
  publishing_limit: { used: number; total: number } | null;
  enabled: boolean;
  post_times: string[];
}

export interface InstagramRouteStatus extends InstagramAccountStatus {
  account: string;
  next_post: string | null;
}

export interface InstagramStatusResponse {
  accounts: Record<string, InstagramAccountStatus>;
  routes: Record<string, InstagramRouteStatus>;
}

export interface AutoStoryJob {
  job_id: string;
  kind: string;
  state: 'running' | 'done' | 'failed';
  message: string;
  result: unknown;
  error: string | null;
}

// Story Library (AUTO_STORY_PLAN.md §7, brief L3): found stories, their
// rights verdict, and the adaptation into the creator's style.
export interface StoryRights {
  status: 'public_domain' | 'protected' | 'unknown' | string;
  death_year?: number | null;
  source?: string;
  note?: string;
}

export interface StoryCandidate {
  title: string;
  author: string;
  language: string;
  source: string;
  url: string;
  snippet?: string;
  rights?: StoryRights | string | null;
  words_estimate?: number | null;
  death_year?: number | null;
  [key: string]: unknown;
}

export interface StoryEntry {
  id: string;
  title: string;
  author: string;
  language: string;
  source: string;
  source_url: string;
  fetched_at: string;
  words: number;
  rights: StoryRights;
  summary?: string;
  first_lines?: string | string[];
}

export interface StoryJob<T = unknown> {
  job_id: string;
  kind: string;
  state: 'running' | 'done' | 'failed';
  message: string;
  result: T | null;
  error: string | null;
}

export interface AdaptJob {
  job_id: string | null;
  kind?: string;
  project_id?: string;
  state: 'running' | 'done' | 'failed' | 'created';
  message: string;
  result: { project_id?: string; [key: string]: unknown } | null;
  error: string | null;
}

export interface AdaptStep {
  name: string;
  agent?: string;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface AdaptStatus {
  project_id: string;
  state: string;
  human_score?: number | null;
  parts?: number | null;
  rights?: StoryRights | string | null;
  mode?: string | null;
  current_step?: string | null;
  job_id?: string | null;
  steps: AdaptStep[];
}

export interface StoryPiece {
  index: number;
  title: string;
  words: number;
}
