import { useCallback, useEffect, useState, type FormEvent } from 'react';
import {
  Compass,
  Send,
  RefreshCw,
  Activity,
  Clock,
  Sparkles,
  Lightbulb,
  RotateCcw,
  ArrowRight,
  Film,
  AlertCircle,
} from 'lucide-react';
import { getJson, postJson, describeError } from '../services/api';
import Markdown from './Markdown';
import { useStudio } from '../state/studio';
import type { TabId } from '../lib/types';

// The Studio Director (docs/STUDIO_DIRECTOR_PLAN.md Part 3):
// - Guidance & What To Do Next (prioritized suggestions)
// - Dynamic Replanning (replan day based on current progress & queue)
// - Live Studio Operations & Stories in progress with remaining time estimates
// - Plan of the day breakdown with MAKE actions
// - Pending approvals & Creator's rules
// - Interactive Quick-Ask prompts

interface DirectorPlanItem {
  channel?: string | null;
  action: string;
  params?: Record<string, unknown>;
  when?: string;
  why?: string;
  needs_approval: boolean;
}

interface DirectorPlan {
  horizon: string;
  generated_at: string;
  items: DirectorPlanItem[];
}

interface DirectorApproval {
  id: string;
  at: string;
  item: DirectorPlanItem;
  state: string;
}

interface DirectorSettings {
  autoplan: boolean;
  provider?: '' | 'claude' | 'gemini' | 'lm_studio';
  provider_status?: { claude?: boolean; gemini?: boolean; lm_studio?: boolean };
}

interface ActiveProcessItem {
  type: string;
  project_id?: string;
  channel?: string;
  title: string;
  current_step: string;
  agent: string;
  status: string;
  detail?: string;
  started_at?: string;
  elapsed?: string;
  estimated_remaining?: string;
  progress_pct?: number;
  latest_log?: string;
}

interface DirectorLiveActivity {
  timestamp: string;
  active_count: number;
  summary: string;
  items: ActiveProcessItem[];
}

export interface DirectorSuggestionItem {
  id: string;
  priority: 'urgent' | 'high' | 'medium' | 'opportunity';
  type: 'review' | 'intro' | 'approval' | 'plan' | 'viral_topic' | 'execute';
  title: string;
  why: string;
  action_label: string;
  action_target?: string;
  data?: Record<string, any>;
}

export interface DirectorSuggestionsResponse {
  timestamp: string;
  primary: DirectorSuggestionItem | null;
  suggestions: DirectorSuggestionItem[];
  stories_in_progress: Array<{
    channel?: string;
    title: string;
    current_step: string;
    agent: string;
    elapsed?: string;
    estimated_remaining?: string;
    progress_pct?: number;
  }>;
  active_count: number;
  plan_items: DirectorPlanItem[];
}

interface DirectorMemory {
  promises?: Array<{ id: string; text: string; state?: string }>;
  incidents?: Array<{ id: string; problem?: string; cause?: string; fix?: string; worked?: boolean | null }>;
  tickets?: Array<{ file: string; title?: string; state?: string; at?: string }>;
  fixes_today?: Array<{ action: string; by?: string; ran?: boolean; ok?: boolean; error?: string; refused?: string; result?: unknown }>;
  conversation?: unknown[];
}

interface DirectorDiagnosis {
  hypotheses?: Array<{ cause: string; evidence?: string; confidence?: number | string }>;
  ran?: Array<{ action?: string; ok?: boolean; refused?: string; error?: string }>;
  approvals?: Array<{ id?: string; action?: string; item?: { action?: string } } | string>;
  ticket?: string | { file?: string } | null;
  incident_id?: string;
  resolved?: unknown[];
  reply?: string;
}

const POLL_MS = 30_000;
const ACTIVITY_POLL_MS = 5 * 60 * 1000; // 5 mins auto-refresh

const CHANNEL_COLORS: Record<string, string> = {
  Life3Baje: '#f59e0b',
  Raat3Baje: '#ef4444',
  Beyond3Baje: '#8b5cf6',
};

const QUICK_PROMPTS = [
  'What should I do next?',
  'Replan today’s work based on current progress',
  'What stories are in progress right now?',
  'What are our top viral story topics?',
];

function estimateRemaining(
  stepName: string,
  agent: string,
  logs: string[] = [],
  startedAt?: string,
  targetMinutes?: number
): { remaining: string; pct: number } {
  if (!startedAt) return { remaining: '', pct: 0 };
  const dt = new Date(startedAt).getTime();
  const elapsedSec = Math.max(0, Math.floor((Date.now() - dt) / 1000));

  const step = (stepName || '').toLowerCase();
  const ag = (agent || '').toLowerCase();

  let partProgress: [number, number] | null = null;
  for (let i = logs.length - 1; i >= 0; i--) {
    const m = logs[i].match(/(?:section|part)\s+(\d+)\s*(?:\/|of)\s*(\d+)/i);
    if (m) {
      const curr = parseInt(m[1], 10);
      const total = parseInt(m[2], 10);
      if (total > 0 && curr <= total) {
        partProgress = [curr, total];
        break;
      }
    }
  }

  let totalSec = 180;
  if (step.includes('strategist') || step.includes('planning')) {
    totalSec = 90;
  } else if (step.includes('research') || step.includes('collection')) {
    totalSec = 240;
  } else if (step.includes('script') || step.includes('story') || ag.includes('writer')) {
    if (partProgress) {
      const [curr, total] = partProgress;
      const remParts = Math.max(0, total - curr);
      totalSec = Math.max(elapsedSec + remParts * 150, 300);
    } else if (targetMinutes && targetMinutes >= 15) {
      totalSec = Math.floor(targetMinutes * 50);
    } else {
      totalSec = 220;
    }
  } else if (step.includes('short')) {
    totalSec = 120;
  } else if (step.includes('visual') || step.includes('prompt')) {
    totalSec = 120;
  } else if (step.includes('sound') || step.includes('timeline')) {
    totalSec = 65;
  } else if (step.includes('narration') || ag.includes('editor')) {
    if (partProgress) {
      const [curr, total] = partProgress;
      const remParts = Math.max(0, total - curr);
      totalSec = Math.max(elapsedSec + remParts * 110, 200);
    } else {
      totalSec = 500;
    }
  } else if (step.includes('seo') || step.includes('thumbnail')) {
    totalSec = 240;
  } else if (step.includes('render')) {
    totalSec = 600;
  } else if (step.includes('transcribe')) {
    totalSec = 90;
  }

  const remSec = totalSec - elapsedSec;
  if (remSec <= 0 || (partProgress && partProgress[0] === partProgress[1])) {
    return { remaining: 'finishing up…', pct: 95 };
  }
  const pct = Math.min(94, Math.max(5, Math.floor((elapsedSec / totalSec) * 100)));
  const mins = Math.floor(remSec / 60);
  const secs = remSec % 60;
  const remaining = mins > 0 ? `~${mins}m ${secs}s remaining` : `~${secs}s remaining`;
  return { remaining, pct };
}

function creatorRulesBody(markdown: string): string {
  const m = markdown.match(/##\s*Creator's rules\s*\n+([\s\S]*?)(?=\n##\s|$)/i);
  return m ? m[1].trim() : '';
}

export default function DirectorPanel() {
  const { navigate, toast } = useStudio();
  const [briefing, setBriefing] = useState<string | null>(null);
  const [plan, setPlan] = useState<DirectorPlan | null>(null);
  const [approvals, setApprovals] = useState<DirectorApproval[]>([]);
  const [rulesDoc, setRulesDoc] = useState<string>('');
  const [creatorRules, setCreatorRules] = useState<string>('');
  const [settings, setSettings] = useState<DirectorSettings | null>(null);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [message, setMessage] = useState('');
  const [reply, setReply] = useState<string | null>(null);
  const [replyMeta, setReplyMeta] = useState<{ provider?: string; turns?: number; simulated?: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [mission, setMission] = useState<string>('');
  const [memory, setMemory] = useState<DirectorMemory>({});
  const [diagnosis, setDiagnosis] = useState<DirectorDiagnosis | null>(null);
  const [approvedFixes, setApprovedFixes] = useState<DirectorApproval[]>([]);

  // Suggestions state
  const [suggestions, setSuggestions] = useState<DirectorSuggestionsResponse | null>(null);
  const [loadingSuggestions, setLoadingSuggestions] = useState(false);

  // Live Activity state
  const [activity, setActivity] = useState<DirectorLiveActivity | null>(null);
  const [loadingActivity, setLoadingActivity] = useState<boolean>(false);
  const [lastActivityFetch, setLastActivityFetch] = useState<Date | null>(null);

  const loadBriefing = useCallback(() => {
    getJson<{ date: string; markdown: string }>('/api/director/briefing')
      .then((r) => setBriefing(r.markdown)).catch(() => setBriefing(null));
  }, []);

  const loadApprovals = useCallback(() => {
    getJson<{ approvals: DirectorApproval[] }>('/api/director/approvals?state=pending')
      .then((r) => setApprovals(r.approvals || [])).catch(() => setApprovals([]));
  }, []);

  const loadApprovedFixes = useCallback(() => {
    getJson<{ approvals: Array<DirectorApproval & { result?: { rollback?: DirectorPlanItem } }> }>('/api/director/approvals?state=approved')
      .then((r) => setApprovedFixes((r.approvals || []).filter((a) => {
        const res = (a as { result?: { rollback?: unknown } }).result;
        return a.item?.action === 'fix_set_config' && !!res?.rollback;
      }).slice(-5)))
      .catch(() => setApprovedFixes([]));
  }, []);

  const loadMission = useCallback(() => {
    getJson<{ mission?: string }>('/api/director/mission')
      .then((r) => setMission(r?.mission || '')).catch(() => undefined);
  }, []);

  const loadMemory = useCallback(() => {
    getJson<DirectorMemory>('/api/director/memory')
      .then((r) => setMemory(r || {})).catch(() => undefined);
  }, []);

  const loadSettings = useCallback(() => {
    getJson<DirectorSettings>('/api/director/settings').then(setSettings).catch(() => setSettings(null));
  }, []);

  const loadRules = useCallback(() => {
    getJson<{ rules: string }>('/api/director/rules')
      .then((r) => { setRulesDoc(r.rules || ''); setCreatorRules(creatorRulesBody(r.rules || '')); })
      .catch(() => undefined);
  }, []);

  const loadSuggestions = useCallback(() => {
    setLoadingSuggestions(true);
    getJson<DirectorSuggestionsResponse>('/api/director/suggestions')
      .then((res) => {
        setSuggestions(res);
        if (res.plan_items && (!plan || !plan.items?.length)) {
          setPlan({ horizon: 'day', generated_at: res.timestamp, items: res.plan_items });
        }
      })
      .catch(() => {
        // Fallback synthesis if endpoint not ready yet
        setSuggestions(null);
      })
      .finally(() => setLoadingSuggestions(false));
  }, [plan]);

  const loadActivity = useCallback(() => {
    setLoadingActivity(true);
    getJson<DirectorLiveActivity>('/api/director/live_activity')
      .then((r) => {
        setActivity(r);
        setLastActivityFetch(new Date());
      })
      .catch(async () => {
        // Fallback: Synthesize live activity from /api/projects and /api/longform/nightly
        try {
          const [projects, lf] = await Promise.all([
            getJson<Array<Record<string, any>>>('/api/projects').catch(() => []),
            getJson<Record<string, any>>('/api/longform/nightly').catch(() => ({})),
          ]);
          const items: ActiveProcessItem[] = [];
          const seen = new Set<string>();

          for (const p of projects || []) {
            if (p.status === 'completed' || p.status === 'archived') continue;
            const history = p.steps_history || [];
            const runningStep = history.find((h: any) => h.status === 'running');
            if (runningStep) {
              const startedAt = runningStep.started_at;
              let elapsed = '';
              if (startedAt) {
                const diffSec = Math.max(0, Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000));
                const mins = Math.floor(diffSec / 60);
                const secs = diffSec % 60;
                elapsed = mins > 0 ? `${mins}m ${secs}s` : `${secs}s`;
              }
              const title = p.name || p.id;
              seen.add(title.trim().toLowerCase());
              const logs = runningStep.logs || [];
              const { remaining, pct } = estimateRemaining(
                runningStep.step_name || p.current_step,
                runningStep.agent_name || 'Agent',
                logs,
                startedAt,
                p.metadata?.target_duration_minutes
              );
              items.push({
                type: 'project_workflow',
                project_id: p.id,
                channel: p.brand,
                title,
                current_step: runningStep.step_name || p.current_step,
                agent: runningStep.agent_name || 'Agent',
                status: 'running',
                detail: `Workflow: ${p.workflow_name || 'default'}`,
                started_at: startedAt,
                elapsed,
                estimated_remaining: remaining,
                progress_pct: pct,
                latest_log: logs.length ? logs[logs.length - 1] : undefined,
              });
            }
          }

          const lfObj = (lf as any) || {};
          if (lfObj?.status?.state === 'running') {
            for (const t of lfObj.status.tasks || []) {
              const stage = t.stage;
              const topic = (t.topic || '').trim();
              if (stage && !['queued', 'completed', 'done', 'failed'].includes(stage)) {
                if (topic && seen.has(topic.toLowerCase())) continue;
                const { remaining, pct } = estimateRemaining(
                  stage,
                  'Workflow Engine',
                  [],
                  lfObj.status.started_at,
                  t.minutes
                );
                items.push({
                  type: 'longform_episode',
                  channel: t.channel,
                  title: topic || `${t.channel} Slot ${t.slot}`,
                  current_step: stage,
                  agent: 'Workflow Engine',
                  status: 'running',
                  detail: `${t.minutes || ''}m story episode`,
                  started_at: lfObj.status.started_at,
                  estimated_remaining: remaining,
                  progress_pct: pct,
                  latest_log: t.detail || undefined,
                });
              }
            }
          }

          const parts = items.map((it) => {
            const chan = it.channel ? `[${it.channel}] ` : '';
            const ag = it.agent ? ` (${it.agent})` : '';
            const el = it.elapsed ? ` (${it.elapsed} in)` : '';
            const rem = it.estimated_remaining ? ` · ${it.estimated_remaining}` : '';
            return `${chan}'${it.title}' is on step '${it.current_step}'${ag}${el}${rem}`;
          });

          setActivity({
            timestamp: new Date().toISOString(),
            active_count: items.length,
            summary: items.length
              ? `Active right now (${items.length}): ${parts.join('; ')}.`
              : 'Studio is currently idle. No background processes or pipeline steps are running.',
            items,
          });
          setLastActivityFetch(new Date());
        } catch (err) {
          console.warn('Fallback live activity synthesis failed', err);
        }
      })
      .finally(() => setLoadingActivity(false));
  }, []);

  useEffect(() => {
    loadBriefing();
    loadApprovals();
    loadSettings();
    loadRules();
    loadMission();
    loadMemory();
    loadApprovedFixes();
    loadActivity();
    loadSuggestions();

    const id = setInterval(loadApprovals, POLL_MS);
    const actId = setInterval(loadActivity, ACTIVITY_POLL_MS);
    const sugId = setInterval(loadSuggestions, ACTIVITY_POLL_MS);
    return () => {
      clearInterval(id);
      clearInterval(actId);
      clearInterval(sugId);
    };
  }, [loadBriefing, loadApprovals, loadSettings, loadRules, loadMission, loadMemory, loadApprovedFixes, loadActivity, loadSuggestions]);

  const run = async (key: string, fn: () => Promise<unknown>) => {
    if (busy[key]) return;
    setBusy((b) => ({ ...b, [key]: true }));
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy((b) => ({ ...b, [key]: false }));
    }
  };

  const makePlan = () => run('plan', async () => {
    const p = await postJson<DirectorPlan>('/api/director/plan', { horizon: 'day' });
    setPlan(p);
    loadBriefing();
    loadSuggestions();
  });

  const replanDay = () => run('replan', async () => {
    try {
      const p = await postJson<DirectorPlan>('/api/director/replan', { horizon: 'day' });
      setPlan(p);
    } catch {
      // Fallback to standard plan
      const p = await postJson<DirectorPlan>('/api/director/plan', { horizon: 'day' });
      setPlan(p);
    }
    loadBriefing();
    loadSuggestions();
    loadActivity();
    toast('Director replanned today’s lineup based on studio progress', 'success');
  });

  const actOnPlan = () => run('act', async () => {
    await postJson('/api/director/act', {});
    loadApprovals();
    loadBriefing();
    loadSuggestions();
    loadActivity();
  });

  const approve = (id: string) => run(`approve-${id}`, async () => {
    await postJson(`/api/director/approvals/${encodeURIComponent(id)}/approve`, {});
    loadApprovals();
    loadSuggestions();
  });

  const decline = (id: string) => {
    const reason = window.prompt('Reason for declining this?', '') || '';
    return run(`decline-${id}`, async () => {
      await postJson(`/api/director/approvals/${encodeURIComponent(id)}/decline`, { reason });
      loadApprovals();
      loadSuggestions();
    });
  };

  const relearn = () => run('learn', async () => {
    const r = await postJson<{ rules: string }>('/api/director/learn', {});
    setRulesDoc(r.rules || '');
    setCreatorRules(creatorRulesBody(r.rules || ''));
  });

  const saveCreatorRules = () => run('save-rules', async () => {
    const r = await postJson<{ rules: string }>('/api/director/rules', { creator_rules: creatorRules });
    setRulesDoc(r.rules || '');
  });

  const saveMission = () => run('save-mission', async () => {
    const r = await postJson<{ mission?: string }>('/api/director/mission', { text: mission });
    if (typeof r?.mission === 'string') setMission(r.mission);
  });

  const diagnose = () => {
    const problem = message.trim();
    if (!problem) return;
    return run('diagnose', async () => {
      const r = await postJson<DirectorDiagnosis>('/api/director/diagnose', { problem });
      setDiagnosis(r || null);
      setReply(r?.reply || null);
      setReplyMeta(null);
      loadMemory();
      loadApprovals();
      loadApprovedFixes();
    });
  };

  const markPromiseDone = (id: string) => run(`promise-${id}`, async () => {
    await postJson(`/api/director/promises/${encodeURIComponent(id)}/done`, {});
    loadMemory();
  });

  const closeTicket = (file: string) => run(`ticket-${file}`, async () => {
    await postJson(`/api/director/tickets/${encodeURIComponent(file)}/close`, {});
    loadMemory();
  });

  const clearConversation = () => run('clear-convo', async () => {
    await postJson('/api/director/conversation/clear', {});
    setReply(null);
    setDiagnosis(null);
    loadMemory();
  });

  const undoFix = (a: DirectorApproval) => run(`undo-${a.id}`, async () => {
    const rollback = (a as unknown as { result?: { rollback?: DirectorPlanItem } }).result?.rollback;
    if (!rollback) return;
    const created = await postJson<{ id: string }>('/api/director/approvals', { item: rollback });
    await postJson(`/api/director/approvals/${encodeURIComponent(created.id)}/approve`, {});
    loadApprovals();
    loadApprovedFixes();
    loadMemory();
  });

  const toggleAutoplan = async () => {
    if (!settings) return;
    const saved = await postJson<DirectorSettings>('/api/director/settings', { autoplan: !settings.autoplan });
    setSettings(prev => ({ ...(prev || {}), ...saved, provider_status: prev?.provider_status }));
  };

  const setProvider = async (p: string) => {
    try {
      const saved = await postJson<DirectorSettings>('/api/director/settings', { provider: p });
      setSettings(prev => ({ ...(prev || {}), ...saved, provider_status: prev?.provider_status }));
    } catch { /* keep current */ }
  };

  const askWithText = (text: string) => {
    setMessage(text);
    setReplyMeta(null);
    run('ask', async () => {
      const r = await postJson<{ reply: string; provider?: string; turns?: number; simulated?: boolean }>('/api/director/ask', { message: text });
      setReply(r.reply);
      setReplyMeta({ provider: r.provider, turns: r.turns, simulated: r.simulated });
      setMessage('');
      loadRules();
      loadMemory();
      loadSuggestions();
    });
  };

  const ask = async (e: FormEvent) => {
    e.preventDefault();
    if (!message.trim() || busy.ask) return;
    askWithText(message.trim());
  };

  const handleSuggestionAction = (item: DirectorSuggestionItem) => {
    if (item.action_target) {
      navigate(item.action_target as TabId);
      return;
    }
    if (item.type === 'execute') {
      actOnPlan();
      return;
    }
    if (item.type === 'plan') {
      replanDay();
      return;
    }
  };

  const priorityColor = (p: string) => {
    switch (p) {
      case 'urgent': return '#ef4444';
      case 'high': return '#f59e0b';
      case 'opportunity': return '#8b5cf6';
      default: return '#38bdf8';
    }
  };

  return (
    <div className="panel-card">
      {/* Top Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Compass size={22} style={{ color: '#38bdf8' }} /> Studio Director
        </h3>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: '0.82rem', color: 'var(--text-primary)', cursor: 'pointer' }}>
            <input type="checkbox" checked={!!settings?.autoplan} onChange={toggleAutoplan} disabled={!settings}
              style={{ width: 15, height: 15, accentColor: '#10b981', cursor: 'pointer' }} />
            Auto-plan nightly
          </label>
          <div title="Model for Director chat and planning; falls back if down" style={{ display: 'inline-flex', gap: 0, borderRadius: 6, overflow: 'hidden', border: '1px solid var(--border-color, rgba(148,163,184,0.35))' }}>
            {([['', 'Auto'], ['claude', 'Claude'], ['gemini', 'Gemini'], ['lm_studio', 'Local Gemma']] as const).map(([p, label]) => {
              const active = (settings?.provider || '') === p;
              const st = p ? settings?.provider_status?.[p as 'claude' | 'gemini' | 'lm_studio'] : undefined;
              return (
                <button key={p || 'auto'} type="button" disabled={!settings} onClick={() => setProvider(p)}
                  style={{
                    padding: '4px 10px', fontSize: '0.8rem', border: 'none', cursor: 'pointer',
                    display: 'inline-flex', alignItems: 'center', gap: 5,
                    background: active ? 'linear-gradient(135deg, #0284c7 0%, #2563eb 100%)' : 'transparent',
                    color: active ? '#fff' : 'var(--text-primary)', fontWeight: active ? 600 : 400,
                  }}>
                  {p && st !== undefined && (
                    <span style={{ width: 7, height: 7, borderRadius: '50%', background: st ? '#10b981' : '#ef4444', display: 'inline-block' }} />
                  )}
                  {label}
                </button>
              );
            })}
          </div>
          <button
            type="button"
            className="btn"
            style={{
              padding: '5px 12px',
              fontSize: '0.82rem',
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              background: 'linear-gradient(135deg, #0284c7 0%, #2563eb 100%)',
              color: '#fff',
              fontWeight: 600,
            }}
            disabled={!!busy.replan}
            onClick={replanDay}
            title="Recalculate today's production plan based on active stories and completed deliverables"
          >
            <RotateCcw size={14} className={busy.replan ? 'spin' : ''} />
            <span>{busy.replan ? 'Replanning…' : 'Replan Day'}</span>
          </button>
          <button type="button" className="btn btn-outline" style={{ padding: '5px 10px', fontSize: '0.82rem' }} disabled={!!busy.plan} onClick={makePlan}>
            {busy.plan ? 'Planning…' : 'Plan today'}
          </button>
          <button type="button" className="btn btn-outline" style={{ padding: '5px 10px', fontSize: '0.82rem' }} disabled={!!busy.act || !plan} onClick={actOnPlan}>
            {busy.act ? 'Running…' : 'Run MAKE items'}
          </button>
          <button type="button" className="btn btn-outline" style={{ padding: '5px 10px', fontSize: '0.82rem' }} disabled={!!busy.learn} onClick={relearn}>
            {busy.learn ? 'Learning…' : 'Re-learn rules'}
          </button>
        </div>
      </div>

      {error && <div style={{ color: '#f87171', fontSize: '0.85rem', marginTop: 10 }}>{error}</div>}

      {/* Director's Strategic Guidance ("What To Do Next") */}
      {suggestions?.primary && (
        <div style={{
          marginTop: 14,
          padding: '14px 16px',
          borderRadius: 10,
          background: 'linear-gradient(135deg, rgba(37, 99, 235, 0.12) 0%, rgba(147, 51, 234, 0.1) 100%)',
          border: '1px solid rgba(56, 189, 248, 0.3)',
          boxShadow: '0 4px 14px rgba(0, 0, 0, 0.18)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Sparkles size={16} style={{ color: '#38bdf8' }} />
              <strong style={{ fontSize: '0.88rem', color: '#f8fafc', letterSpacing: '0.02em', textTransform: 'uppercase' }}>
                Director's Guidance · What To Do Next
              </strong>
            </div>
            <span style={{
              fontSize: '0.72rem',
              fontWeight: 700,
              padding: '2px 8px',
              borderRadius: 12,
              textTransform: 'uppercase',
              color: priorityColor(suggestions.primary.priority),
              background: `${priorityColor(suggestions.primary.priority)}18`,
              border: `1px solid ${priorityColor(suggestions.primary.priority)}40`,
            }}>
              {suggestions.primary.priority} Priority
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ flex: 1, minWidth: 260 }}>
              <div style={{ fontSize: '0.96rem', fontWeight: 600, color: 'var(--text-primary)', marginBottom: 4 }}>
                {suggestions.primary.title}
              </div>
              <div style={{ fontSize: '0.84rem', color: 'var(--text-secondary)', lineHeight: 1.45 }}>
                {suggestions.primary.why}
              </div>
            </div>
            <button
              type="button"
              className="btn"
              onClick={() => handleSuggestionAction(suggestions.primary!)}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
                padding: '7px 14px',
                fontSize: '0.84rem',
                fontWeight: 600,
                background: 'linear-gradient(135deg, #38bdf8 0%, #3b82f6 100%)',
                color: '#fff',
                boxShadow: '0 2px 8px rgba(56, 189, 248, 0.35)',
                whiteSpace: 'nowrap',
              }}
            >
              <span>{suggestions.primary.action_label}</span>
              <ArrowRight size={14} />
            </button>
          </div>

          {/* Secondary suggestions */}
          {suggestions.suggestions && suggestions.suggestions.length > 1 && (
            <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid rgba(255, 255, 255, 0.08)' }}>
              <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6, display: 'flex', alignItems: 'center', gap: 5 }}>
                <Lightbulb size={12} /> OTHER ACTIONABLE ITEMS ({suggestions.suggestions.length - 1}):
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {suggestions.suggestions.slice(1, 4).map((sugg) => (
                  <div
                    key={sugg.id}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: 8,
                      fontSize: '0.8rem',
                      padding: '4px 8px',
                      borderRadius: 6,
                      background: 'rgba(0, 0, 0, 0.2)',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, overflow: 'hidden' }}>
                      <span style={{
                        fontSize: '0.68rem',
                        fontWeight: 700,
                        padding: '1px 5px',
                        borderRadius: 4,
                        color: priorityColor(sugg.priority),
                        background: `${priorityColor(sugg.priority)}15`,
                      }}>
                        {sugg.priority}
                      </span>
                      <span style={{ color: 'var(--text-primary)', textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                        {sugg.title}
                      </span>
                    </div>
                    <button
                      type="button"
                      className="btn btn-outline"
                      onClick={() => handleSuggestionAction(sugg)}
                      style={{ padding: '2px 8px', fontSize: '0.73rem', whiteSpace: 'nowrap' }}
                    >
                      {sugg.action_label}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Live Studio Operations & Stories in Progress */}
      <div style={{
        marginTop: 14,
        padding: '12px 14px',
        borderRadius: 8,
        background: 'var(--bg-subcard)',
        border: '1px solid var(--border-card)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{
              width: 9,
              height: 9,
              borderRadius: '50%',
              backgroundColor: (activity?.active_count || 0) > 0 ? '#10b981' : 'var(--text-muted)',
              boxShadow: (activity?.active_count || 0) > 0 ? '0 0 8px #10b981' : 'none',
              display: 'inline-block',
            }} />
            <strong style={{ fontSize: '0.9rem', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
              <Activity size={16} /> What's Going On · Stories In Progress
            </strong>
            <span style={{
              fontSize: '0.72rem',
              fontWeight: 600,
              padding: '2px 8px',
              borderRadius: 12,
              background: (activity?.active_count || 0) > 0 ? 'rgba(16, 185, 129, 0.15)' : 'rgba(255, 255, 255, 0.05)',
              color: (activity?.active_count || 0) > 0 ? '#10b981' : 'var(--text-secondary)',
              border: `1px solid ${(activity?.active_count || 0) > 0 ? 'rgba(16, 185, 129, 0.3)' : 'var(--border-subtle)'}`,
            }}>
              {(activity?.active_count || 0) > 0 ? `${activity?.active_count} active` : 'Idle'}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 4 }}>
              <Clock size={12} />
              {lastActivityFetch ? `Checked ${lastActivityFetch.toLocaleTimeString()}` : 'Checking…'}
              <span style={{ opacity: 0.6 }}>(auto-refreshes 5m)</span>
            </span>
            <button
              type="button"
              className="btn btn-outline"
              disabled={loadingActivity || loadingSuggestions}
              onClick={() => { loadActivity(); loadSuggestions(); }}
              title="Click to check current processes and stories right now"
              style={{ padding: '3px 9px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: 4 }}
            >
              <RefreshCw size={12} className={(loadingActivity || loadingSuggestions) ? 'spin' : ''} />
              <span>{(loadingActivity || loadingSuggestions) ? 'Checking…' : 'Refresh'}</span>
            </button>
          </div>
        </div>

        {activity?.summary && (
          <div style={{
            fontSize: '0.82rem',
            color: 'var(--text-secondary)',
            lineHeight: 1.4,
            marginBottom: activity.items?.length ? 10 : 0,
            padding: '6px 10px',
            borderRadius: 6,
            background: 'var(--bg-card)',
            borderLeft: '3px solid var(--accent-primary)',
          }}>
            {activity.summary}
          </div>
        )}

        {activity?.items && activity.items.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {activity.items.map((item, idx) => {
              const chanColor = item.channel ? CHANNEL_COLORS[item.channel] || '#38bdf8' : '#38bdf8';
              return (
                <div
                  key={idx}
                  style={{
                    padding: '8px 10px',
                    borderRadius: 6,
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border-subtle)',
                    fontSize: '0.83rem',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      {item.channel && (
                        <span style={{
                          fontWeight: 700,
                          fontSize: '0.72rem',
                          padding: '1px 6px',
                          borderRadius: 4,
                          background: `${chanColor}20`,
                          color: chanColor,
                          border: `1px solid ${chanColor}50`,
                        }}>
                          {item.channel}
                        </span>
                      )}
                      <strong style={{ color: 'var(--text-primary)' }}>{item.title}</strong>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      {item.elapsed && (
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                          ⏱️ {item.elapsed}
                        </span>
                      )}
                      {item.estimated_remaining && (
                        <span style={{
                          fontSize: '0.72rem',
                          fontWeight: 600,
                          color: '#c084fc',
                          background: 'rgba(192, 132, 252, 0.12)',
                          border: '1px solid rgba(192, 132, 252, 0.28)',
                          padding: '1px 6px',
                          borderRadius: 4,
                        }}>
                          ⏳ {item.estimated_remaining}
                        </span>
                      )}
                      <span style={{
                        fontWeight: 600,
                        fontSize: '0.72rem',
                        padding: '2px 8px',
                        borderRadius: 4,
                        background: 'rgba(56, 189, 248, 0.15)',
                        color: '#38bdf8',
                        border: '1px solid rgba(56, 189, 248, 0.3)',
                      }}>
                        {item.current_step}
                      </span>
                    </div>
                  </div>

                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 4, fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                    <span>
                      Agent: <strong style={{ color: 'var(--accent-primary)' }}>{item.agent}</strong>
                      {item.detail ? ` · ${item.detail}` : ''}
                    </span>
                    {item.progress_pct !== undefined && (
                      <span style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-muted)' }}>
                        {item.progress_pct}%
                      </span>
                    )}
                  </div>

                  {item.progress_pct !== undefined && (
                    <div style={{ marginTop: 6, marginBottom: 2 }}>
                      <div style={{
                        height: 4,
                        borderRadius: 2,
                        background: 'rgba(255, 255, 255, 0.08)',
                        overflow: 'hidden',
                        width: '100%',
                      }}>
                        <div style={{
                          height: '100%',
                          width: `${Math.min(100, Math.max(5, item.progress_pct))}%`,
                          background: 'linear-gradient(90deg, #38bdf8 0%, #818cf8 50%, #c084fc 100%)',
                          borderRadius: 2,
                          transition: 'width 0.4s ease',
                        }} />
                      </div>
                    </div>
                  )}

                  {item.latest_log && (
                    <div style={{
                      marginTop: 4,
                      fontSize: '0.72rem',
                      color: 'var(--text-muted)',
                      fontFamily: 'monospace',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      background: 'var(--bg-app)',
                      padding: '2px 6px',
                      borderRadius: 4,
                    }}>
                      ▶ {item.latest_log}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : null}
      </div>

      {/* Plan of the Day */}
      {plan && plan.items && plan.items.length > 0 && (
        <div style={{
          marginTop: 14,
          padding: '12px 14px',
          borderRadius: 8,
          background: 'var(--bg-subcard)',
          border: '1px solid var(--border-card)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <div style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: 6 }}>
              <Film size={16} style={{ color: '#38bdf8' }} /> Plan of the Day ({plan.items.length} items)
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <button
                type="button"
                className="btn btn-outline"
                style={{ padding: '3px 8px', fontSize: '0.75rem' }}
                onClick={replanDay}
                disabled={!!busy.replan}
              >
                🔄 Replan
              </button>
              <button
                type="button"
                className="btn btn-outline"
                style={{ padding: '3px 8px', fontSize: '0.75rem' }}
                onClick={actOnPlan}
                disabled={!!busy.act}
              >
                ▶ Run MAKE items
              </button>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {plan.items.map((item, i) => {
              const chanColor = item.channel ? CHANNEL_COLORS[item.channel] || '#38bdf8' : '#38bdf8';
              return (
                <div
                  key={i}
                  style={{
                    padding: '8px 10px',
                    borderRadius: 6,
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border-subtle)',
                    fontSize: '0.83rem',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{
                        fontWeight: 700,
                        fontSize: '0.72rem',
                        padding: '1px 6px',
                        borderRadius: 4,
                        background: `${chanColor}20`,
                        color: chanColor,
                        border: `1px solid ${chanColor}50`,
                      }}>
                        {item.channel || 'Studio-wide'}
                      </span>
                      <strong style={{ color: 'var(--text-primary)' }}>{item.action}</strong>
                    </div>
                    {item.needs_approval ? (
                      <span style={{
                        fontSize: '0.72rem',
                        fontWeight: 600,
                        color: '#f59e0b',
                        background: 'rgba(245, 158, 11, 0.15)',
                        border: '1px solid rgba(245, 158, 11, 0.3)',
                        padding: '1px 6px',
                        borderRadius: 4,
                      }}>
                        Needs Approval
                      </span>
                    ) : (
                      <span style={{
                        fontSize: '0.72rem',
                        color: '#10b981',
                        background: 'rgba(16, 185, 129, 0.12)',
                        border: '1px solid rgba(16, 185, 129, 0.25)',
                        padding: '1px 6px',
                        borderRadius: 4,
                      }}>
                        Ready
                      </span>
                    )}
                  </div>
                  {item.why && (
                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', marginTop: 4, lineHeight: 1.35 }}>
                      {item.why}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Pending Approvals */}
      {approvals.length > 0 && (
        <div style={{
          marginTop: 14,
          padding: '12px 14px',
          borderRadius: 8,
          background: 'rgba(239, 68, 68, 0.08)',
          border: '1px solid rgba(239, 68, 68, 0.25)',
        }}>
          <div style={{ fontWeight: 600, color: '#f87171', marginBottom: 8, fontSize: '0.88rem', display: 'flex', alignItems: 'center', gap: 6 }}>
            <AlertCircle size={16} /> Pending Director Approvals ({approvals.length})
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {approvals.map((a) => (
              <div key={a.id} style={{
                display: 'flex',
                justifyContent: 'space-between',
                gap: 8,
                alignItems: 'center',
                padding: '8px 10px',
                borderRadius: 6,
                background: 'var(--bg-card)',
                border: '1px solid var(--border-subtle)',
                fontSize: '0.84rem',
              }}>
                <div>
                  <strong style={{ color: 'var(--text-primary)' }}>{a.item?.channel || 'Studio-wide'}</strong>: {a.item?.action}
                  {a.item?.why && <div style={{ fontSize: '0.76rem', color: 'var(--text-secondary)', marginTop: 2 }}>{a.item.why}</div>}
                </div>
                <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
                  <button type="button" className="btn btn-outline" style={{ padding: '3px 10px', fontSize: '0.76rem', color: '#10b981', borderColor: '#10b981' }}
                    disabled={!!busy[`approve-${a.id}`]} onClick={() => approve(a.id)}>Approve</button>
                  <button type="button" className="btn btn-outline" style={{ padding: '3px 10px', fontSize: '0.76rem', color: '#f87171', borderColor: '#f87171' }}
                    disabled={!!busy[`decline-${a.id}`]} onClick={() => decline(a.id)}>Decline</button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Morning Briefing Markdown */}
      {briefing && (
        <div style={{ marginTop: 14, borderTop: '1px solid var(--border-subtle)', paddingTop: 10 }}>
          <Markdown text={briefing} />
        </div>
      )}

      {/* Talk to the Director with Interactive Quick Chips */}
      <div style={{ marginTop: 16, borderTop: '1px solid var(--border-subtle)', paddingTop: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
          <strong style={{ fontSize: '0.9rem', color: 'var(--text-primary)' }}>Talk to the Director</strong>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Ask questions or give standing rules</span>
        </div>

        {/* Quick prompt chips */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
          {QUICK_PROMPTS.map((promptText, idx) => (
            <button
              key={idx}
              type="button"
              className="btn btn-outline"
              disabled={busy.ask}
              onClick={() => askWithText(promptText)}
              style={{
                fontSize: '0.76rem',
                padding: '3px 8px',
                borderRadius: 14,
                background: 'rgba(255, 255, 255, 0.04)',
                border: '1px solid var(--border-subtle)',
                color: 'var(--text-secondary)',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
              }}
            >
              <span>💬 {promptText}</span>
            </button>
          ))}
        </div>

        <form onSubmit={ask} style={{ display: 'flex', gap: 8 }}>
          <input
            className="form-control"
            aria-label="Message to the Director"
            style={{ flex: 1 }}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            placeholder="Ask: 'What should I do next?', 'Replan today', or set a standing rule…"
          />
          <button type="submit" className="btn" disabled={busy.ask || !message.trim()} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <Send size={15} />
            <span>{busy.ask ? 'Thinking…' : 'Ask'}</span>
          </button>
          <button type="button" className="btn btn-outline" onClick={diagnose}
            disabled={!!busy.diagnose || !message.trim()}
            title="Investigate this as a problem: hypotheses, safe fixes, approvals, dev ticket"
            style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
            <span>{busy.diagnose ? 'Diagnosing…' : 'Diagnose'}</span>
          </button>
        </form>

        {diagnosis && (
          <div style={{ marginTop: 10, padding: '10px 14px', borderRadius: 8, background: 'var(--bg-subcard)', border: '1px solid var(--border-card)', fontSize: '0.82rem', color: 'var(--text-primary)' }}>
            {(diagnosis.hypotheses || []).length > 0 && (
              <div style={{ marginBottom: 6 }}>
                <strong>Likely causes</strong>
                {(diagnosis.hypotheses || []).map((h, i) => (
                  <div key={i} style={{ color: 'var(--text-secondary)' }}>
                    {h.cause}{h.confidence != null && h.confidence !== '' ? ` (${typeof h.confidence === 'number' ? `${Math.round(h.confidence <= 1 ? h.confidence * 100 : h.confidence)}%` : h.confidence})` : ''}
                  </div>
                ))}
              </div>
            )}
            {(diagnosis.ran || []).length > 0 && (
              <div style={{ marginBottom: 6 }}>
                <strong>Fixes run</strong>
                {(diagnosis.ran || []).map((f, i) => (
                  <div key={i} style={{ color: f.refused ? '#f59e0b' : f.ok === false ? '#f87171' : '#10b981' }}>
                    {f.action || 'fix'} · {f.refused ? `refused: ${f.refused}` : f.ok === false ? `failed${f.error ? `: ${f.error}` : ''}` : 'ok'}
                  </div>
                ))}
              </div>
            )}
            {(diagnosis.approvals || []).length > 0 && (
              <div style={{ marginBottom: 6, color: '#f59e0b' }}>
                <strong>Queued for your approval</strong>
                {(diagnosis.approvals || []).map((ap, i) => (
                  <div key={i}>{typeof ap === 'string' ? ap : ap.action || ap.item?.action || ap.id || 'approval'}</div>
                ))}
              </div>
            )}
            {diagnosis.ticket && (
              <div style={{ color: 'var(--text-secondary)' }}>
                Dev ticket filed: {typeof diagnosis.ticket === 'string' ? diagnosis.ticket : diagnosis.ticket.file}
              </div>
            )}
          </div>
        )}

        {reply && (
          <div style={{
            marginTop: 10,
            padding: '10px 14px',
            borderRadius: 8,
            background: 'var(--bg-subcard)',
            border: '1px solid var(--border-card)',
            fontSize: '0.85rem',
            color: 'var(--text-primary)',
          }}>
            <Markdown text={reply} />
            {replyMeta && (
              <div style={{ marginTop: 6, fontSize: '0.74rem', color: 'var(--text-secondary)' }}>
                {replyMeta.simulated
                  ? 'no model answered'
                  : `answered by ${replyMeta.provider || 'unknown'}${replyMeta.turns != null ? ` (${replyMeta.turns} turns)` : ''}`}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Mission, goals and plans */}
      <div style={{ marginTop: 14, borderTop: '1px solid var(--border-subtle)', paddingTop: 10 }}>
        <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6, fontSize: '0.88rem' }}>Mission, goals and plans</div>
        <textarea
          className="form-control"
          aria-label="Mission, goals and plans"
          style={{ width: '100%', minHeight: 140, fontFamily: 'inherit', resize: 'vertical' }}
          value={mission}
          onChange={(e) => setMission(e.target.value)}
          placeholder="The Director's mission: goals, how you want it done, upcoming plans, priorities, constraints."
        />
        <button
          type="button"
          className="btn btn-outline"
          style={{ marginTop: 8, padding: '4px 12px', fontSize: '0.8rem' }}
          disabled={!!busy['save-mission']}
          onClick={saveMission}
        >
          {busy['save-mission'] ? 'Saving…' : 'Save Mission'}
        </button>
      </div>

      {/* Creator's Standing Rules */}
      <div style={{ marginTop: 14, borderTop: '1px solid var(--border-subtle)', paddingTop: 10 }}>
        <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6, fontSize: '0.88rem' }}>Creator's rules</div>
        <textarea
          className="form-control"
          aria-label="Creator's rules"
          style={{ width: '100%', minHeight: 70, fontFamily: 'inherit', resize: 'vertical' }}
          value={creatorRules}
          onChange={(e) => setCreatorRules(e.target.value)}
          placeholder="Write your own standing rules for the Director here -- it never overwrites this."
        />
        <button
          type="button"
          className="btn btn-outline"
          style={{ marginTop: 8, padding: '4px 12px', fontSize: '0.8rem' }}
          disabled={!!busy['save-rules']}
          onClick={saveCreatorRules}
        >
          {busy['save-rules'] ? 'Saving…' : 'Save Rules'}
        </button>
      </div>

      {/* Learned Rules */}
      {rulesDoc && (
        <div style={{ marginTop: 14, borderTop: '1px solid var(--border-subtle)', paddingTop: 10 }}>
          <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 6, fontSize: '0.88rem' }}>Learned rules</div>
          <Markdown text={rulesDoc} />
        </div>
      )}

      {/* Memory */}
      <div style={{ marginTop: 14, borderTop: '1px solid var(--border-subtle)', paddingTop: 10, fontSize: '0.82rem' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '0.88rem' }}>Memory</span>
          <button type="button" onClick={clearConversation} disabled={!!busy['clear-convo']}
            style={{ background: 'none', border: 'none', color: 'var(--text-muted)', textDecoration: 'underline', cursor: 'pointer', fontSize: '0.76rem' }}>
            Forget conversation
          </button>
        </div>

        {(() => {
          const promises = (memory.promises || []).filter((p) => !p.state || p.state === 'open');
          const tickets = memory.tickets || [];
          const fixes = memory.fixes_today || [];
          const incidents = (memory.incidents || []).slice(-5);
          const label = { fontWeight: 600, color: 'var(--text-secondary)', margin: '8px 0 4px' } as const;
          const rowStyle = { display: 'flex', justifyContent: 'space-between', gap: 8, alignItems: 'center', padding: '4px 0' } as const;
          const smallBtn = { padding: '2px 8px', fontSize: '0.74rem' } as const;
          return (
            <>
              <div style={label}>Open promises ({promises.length})</div>
              {promises.length === 0 && <div style={{ color: 'var(--text-muted)' }}>None.</div>}
              {promises.map((p) => (
                <div key={p.id} style={rowStyle}>
                  <span style={{ color: 'var(--text-primary)' }}>{p.text}</span>
                  <button type="button" className="btn btn-outline" style={smallBtn}
                    disabled={!!busy[`promise-${p.id}`]} onClick={() => markPromiseDone(p.id)}>Done</button>
                </div>
              ))}

              <div style={label}>Dev tickets ({tickets.length})</div>
              {tickets.length === 0 && <div style={{ color: 'var(--text-muted)' }}>None.</div>}
              {tickets.map((t) => (
                <div key={t.file} style={rowStyle}>
                  <span style={{ color: 'var(--text-primary)' }}>{t.title || t.file} <span style={{ color: 'var(--text-muted)' }}>· {t.state || 'open'}</span></span>
                  {(!t.state || t.state === 'open') && (
                    <button type="button" className="btn btn-outline" style={smallBtn}
                      disabled={!!busy[`ticket-${t.file}`]} onClick={() => closeTicket(t.file)}>Close</button>
                  )}
                </div>
              ))}

              <div style={label}>Fixes today ({fixes.length})</div>
              {fixes.length === 0 && <div style={{ color: 'var(--text-muted)' }}>None.</div>}
              {fixes.map((f, i) => (
                <div key={i} style={{ padding: '2px 0', color: f.refused ? '#f59e0b' : f.ok === false ? '#f87171' : 'var(--text-primary)' }}>
                  {f.action}{f.by ? ` (${f.by})` : ''} · {f.refused ? `refused: ${f.refused}` : f.ok === false ? `failed${f.error ? `: ${f.error}` : ''}` : f.ran === false ? 'not run' : 'ok'}
                </div>
              ))}
              {approvedFixes.map((a) => (
                <div key={a.id} style={rowStyle}>
                  <span style={{ color: 'var(--text-primary)' }}>Approved: {a.item?.action} {a.item?.params ? JSON.stringify(a.item.params).slice(0, 80) : ''}</span>
                  <button type="button" className="btn btn-outline" style={smallBtn}
                    disabled={!!busy[`undo-${a.id}`]} onClick={() => undoFix(a)}>Undo</button>
                </div>
              ))}

              <div style={label}>Recent incidents</div>
              {incidents.length === 0 && <div style={{ color: 'var(--text-muted)' }}>None.</div>}
              {incidents.map((inc) => (
                <div key={inc.id} style={{ padding: '2px 0', color: 'var(--text-primary)' }}>
                  {inc.problem} → {inc.fix || inc.cause || 'no fix yet'}
                  {inc.worked != null && <span style={{ color: inc.worked ? '#10b981' : '#f87171' }}> · {inc.worked ? 'worked' : 'did not work'}</span>}
                </div>
              ))}
            </>
          );
        })()}
      </div>
    </div>
  );
}

