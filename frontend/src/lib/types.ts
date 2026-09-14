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

export interface HealthInfo {
  status: string;
  app?: string;
  version?: string;
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
  | 'analyze'
  | 'agent_creator_studio'
  | 'agents_group_chat'
  | 'ai_workforce'
  | 'departments'
  | 'health'
  | 'settings';

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
