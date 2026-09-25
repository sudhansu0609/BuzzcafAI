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
}

export interface StudioSettings {
  selected_provider?: string;
  gemini_model?: string;
  gemini_api_key_set?: boolean;
  openai_api_key_set?: boolean;
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
  | 'board'
  | 'analyze'
  | 'research'
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

// GET /api/projects/{id}/produce_video/status (app/api/produce_api.py). No
// job queue backs this -- it is an in-memory dict, so `idle` also covers "the
// backend restarted mid-run".
export interface ProduceVideoStatus {
  state: 'idle' | 'starting' | 'running' | 'ready' | 'failed';
  message?: string;
  progress?: number;
  error?: string | null;
  buzzedit_job_id?: string;
  output_path?: string | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  report?: Record<string, any> | null;
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
