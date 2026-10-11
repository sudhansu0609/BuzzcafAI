import { useCallback, useEffect, useRef, useState } from 'react';
import { Moon, Play, RotateCw, Save } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';
import NightlyControls, { type NightlyState } from './NightlyControls';

// The long-form half of the nightly run (backend app/services/longform_nightly.py).
// Per channel, the channel strategist plans the video with every Studio tool and
// agent, following the creator's instructions below; research and script then
// run on that plan and stop at Visual Plan for review. The live status comes
// from a file the run rewrites as it goes, so a 03:00 run shows here too.
// Lives on the Scheduler Desk's Long form tab, with its own wake time, hibernate
// and idle settings (its own Windows task; the Shorts tab has another).

type Task = { channel: string; slot: number; stage: string; topic: string | null; project_id: string | null; detail: string };
type LogLine = { at: string; channel: string; text: string };
type RunStatus = {
  state: 'idle' | 'running' | 'done' | 'failed'; trigger?: 'nightly' | 'manual';
  started_at?: string; updated_at?: string; finished_at?: string | null; error?: string | null;
  tasks: Task[]; log: LogLine[];
};
type LongformState = {
  enabled: boolean; channels: string[]; all_channels: string[]; per_channel: number;
  minutes: Record<string, number>; instructions: Record<string, string>; strategists: Record<string, string>; guides: Record<string, string>;
  schedule: Omit<NightlyState, 'enabled'>;
  running: boolean;
  status: RunStatus;
};
type Patch = Partial<Pick<LongformState, 'enabled' | 'channels' | 'per_channel' | 'minutes' | 'instructions'>>
  & Partial<Pick<NightlyState, 'time' | 'hibernate' | 'idle_minutes'>>;

const LINK = { background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: 'var(--accent-primary)', textDecoration: 'underline', font: 'inherit' } as const;

const CHANNEL_COLORS: Record<string, string> = { Life3Baje: '#f59e0b', Raat3Baje: '#ef4444', Beyond3Baje: '#8b5cf6' };

function stageColor(stage: string): string {
  if (stage === 'done') return '#22c55e';
  if (stage === 'failed') return '#f87171';
  if (stage === 'queued' || stage === 'skipped') return 'var(--text-muted)';
  return '#60a5fa'; // planning or a workflow step: in progress
}

export default function LongformScheduler({ onOpenProject }: { onOpenProject: (id: string) => void }) {
  const { toast, refreshProjects, channelFilter } = useStudio();
  const [state, setState] = useState<LongformState | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [logFilter, setLogFilter] = useState<string | null>(null);
  const [showRules, setShowRules] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  const load = useCallback(() => {
    getJson<LongformState>('/api/longform/nightly').then(setState).catch(() => undefined);
  }, []);
  useEffect(load, [load]);

  // While a run is going (Run now here, or the nightly process), poll the live
  // status; refresh the project list when it finishes.
  const live = state?.status.state === 'running';
  useEffect(() => {
    if (!live) return undefined;
    const t = window.setInterval(() => {
      getJson<LongformState>('/api/longform/nightly').then((s) => {
        setState(s);
        if (s.status.state !== 'running') refreshProjects();
      }).catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(t);
  }, [live, refreshProjects]);

  const logLength = state?.status.log.length ?? 0;
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logLength]);

  const save = async (patch: Patch) => {
    try {
      setState(await postJson<LongformState>('/api/longform/nightly', patch));
      return true;
    } catch (e) {
      toast(describeError(e), 'error');
      return false;
    }
  };

  const saveInstructions = async (ch: string) => {
    if (await save({ instructions: { [ch]: drafts[ch] ?? '' } })) {
      setDrafts((d) => {
        const next = { ...d };
        delete next[ch];
        return next;
      });
      toast(`${ch} instructions saved.`, 'success');
    }
  };

  const runNow = async () => {
    try {
      setState(await postJson<LongformState>('/api/longform/nightly/run', {}));
      toast('Long-form run started. Follow it below.', 'success');
    } catch (e) {
      toast(describeError(e), 'error');
    }
  };

  if (!state) return null;
  const busy = state.running || live;
  const status = state.status;
  const toggleChannel = (ch: string, on: boolean) =>
    save({ channels: on ? state.all_channels.filter((c) => c === ch || state.channels.includes(c)) : state.channels.filter((c) => c !== ch) });

  return (
    <div className="panel-card" style={{ marginBottom: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <h3 className="panel-title" style={{ margin: 0 }}><Moon size={20} /> Long-form scheduler</h3>
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="button" className="btn btn-outline" onClick={load}><RotateCw size={14} /><span>Refresh</span></button>
          <button type="button" className="btn" onClick={runNow} disabled={busy}>
            <Play size={14} /><span>{busy ? 'Running…' : 'Run now'}</span>
          </button>
        </div>
      </div>
      <div style={{ color: 'var(--text-secondary)', fontSize: '0.84rem', margin: '8px 0 12px' }}>
        Every night each channel's strategist plans a video by its channel rules and anything specific you add below. It
        picks the topic (your Topic Vault and Idea Dump first), researches it with every Studio tool and agent, and writes
        a creative brief. Research and script then run on that brief, and the project waits at Visual Plan for you to
        review and record.
      </div>

      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
        <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <input type="number" className="form-control" min={1} max={5} value={state.per_channel}
            onChange={(e) => save({ per_channel: Math.max(1, Math.min(5, Number(e.target.value) || 1)) })} style={{ width: 60 }} />
          per channel
        </label>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12, marginTop: 12 }}>
        {state.all_channels.filter((ch) => !channelFilter || ch === channelFilter).map((ch) => {
          const draft = drafts[ch];
          const text = draft ?? state.instructions[ch] ?? '';
          return (
            <div key={ch} style={{ border: '1px solid var(--border-subtle)', borderTop: `3px solid ${CHANNEL_COLORS[ch]}`, borderRadius: 8, padding: 10 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap' }}>
                <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}>
                  <input type="checkbox" checked={state.channels.includes(ch)} onChange={(e) => toggleChannel(ch, e.target.checked)} style={{ width: 16, height: 16 }} />
                  <span style={{ color: CHANNEL_COLORS[ch], fontWeight: 700 }}>{ch}</span>
                </label>
                <span style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                  <input type="number" className="form-control" min={1} max={180} value={state.minutes[ch] ?? 8}
                    aria-label={`${ch} video length in minutes`}
                    onChange={(e) => save({ minutes: { [ch]: Math.max(1, Math.min(180, Number(e.target.value) || 8)) } })}
                    style={{ width: 64 }} />
                  <span style={{ color: 'var(--text-secondary)', fontSize: '0.82rem' }}>min</span>
                </span>
              </div>
              <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', margin: '4px 0 6px' }}>
                Planned by {state.strategists[ch]} · always follows the{' '}
                <button type="button" style={LINK} onClick={() => setShowRules(showRules === ch ? null : ch)}>
                  {showRules === ch ? 'hide channel rules' : 'channel rules & format'}
                </button>
              </div>
              {showRules === ch && (
                <div style={{ maxHeight: 220, overflowY: 'auto', whiteSpace: 'pre-wrap', fontSize: '0.76rem', lineHeight: 1.45, background: 'var(--bg-secondary, rgba(0,0,0,0.2))', borderRadius: 6, padding: 8, marginBottom: 6 }}>
                  {state.guides[ch] || 'No channel guide found.'}
                </div>
              )}
              <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: 4 }}>Something specific (optional)</div>
              <textarea
                className="form-control"
                rows={5}
                value={text}
                placeholder={`Anything extra for the next ${ch} runs: a topic or season to focus on, a format to use, something to avoid. Wins over the channel rules.`}
                onChange={(e) => setDrafts((d) => ({ ...d, [ch]: e.target.value }))}
                style={{ width: '100%', resize: 'vertical', fontSize: '0.84rem' }}
              />
              {draft !== undefined && draft !== (state.instructions[ch] ?? '') && (
                <button type="button" className="btn" style={{ marginTop: 6 }} onClick={() => saveInstructions(ch)}>
                  <Save size={14} /><span>Save instructions</span>
                </button>
              )}
            </div>
          );
        })}
      </div>

      <NightlyControls
        title="Long-form run — wake the PC, plan and script the videos, hibernate"
        blurb="Windows wakes the computer (even from hibernate) at the time below, runs the long-form batch, offloads every model, then hibernates again — only if no render, ComfyUI job or production item is running, the GPU is idle, and nobody has used the PC for the idle minutes set here. If the Shorts run is still going, this one waits for it. The Shorts scheduler has its own time and settings on the Shorts tab."
        state={{ ...state.schedule, enabled: state.enabled }}
        onSave={(patch) => save(patch)}
      />

      {status.tasks.length > 0 && (
        <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--border-subtle)' }}>
          <div style={{ fontWeight: 700, marginBottom: 6 }}>
            {status.state === 'running' ? 'Running now' : status.state === 'failed' ? 'Last run failed' : 'Last run'}
            <span style={{ fontWeight: 400, color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
              {' · '}{status.trigger === 'manual' ? 'Run now' : 'nightly'} · started {status.started_at}
              {status.finished_at ? ` · finished ${status.finished_at}` : ` · last update ${status.updated_at}`}
            </span>
          </div>
          {status.error && <div style={{ color: '#f87171', fontSize: '0.84rem', marginBottom: 6 }}>{status.error}</div>}
          <div style={{ display: 'grid', gap: 6 }}>
            {status.tasks.map((t) => (
              <div key={`${t.channel}-${t.slot}`} style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', fontSize: '0.84rem' }}>
                <span style={{ color: CHANNEL_COLORS[t.channel], fontWeight: 600, minWidth: 96 }}>
                  {t.channel}{state.per_channel > 1 ? ` #${t.slot}` : ''}
                </span>
                <span style={{ color: stageColor(t.stage), border: `1px solid ${stageColor(t.stage)}`, borderRadius: 999, padding: '1px 8px', fontSize: '0.76rem', whiteSpace: 'nowrap' }}>
                  {t.stage}
                </span>
                {t.project_id
                  ? <button type="button" style={LINK} onClick={() => onOpenProject(t.project_id as string)}>{t.topic}</button>
                  : <span>{t.topic || ''}</span>}
                {t.detail && <span style={{ color: 'var(--text-secondary)' }}>{t.detail}</span>}
                {t.project_id && (
                  <button type="button" style={{ ...LINK, fontSize: '0.78rem' }} onClick={() => setLogFilter(logFilter === t.project_id ? null : t.project_id)}>
                    {logFilter === t.project_id ? 'hide log' : 'log'}
                  </button>
                )}
              </div>
            ))}
          </div>
          <div
            ref={logRef}
            style={{ marginTop: 10, maxHeight: 220, overflowY: 'auto', background: 'var(--bg-secondary, rgba(0,0,0,0.2))', borderRadius: 8, padding: '8px 10px', fontFamily: 'ui-monospace, Consolas, monospace', fontSize: '0.76rem', lineHeight: 1.5 }}
          >
            {status.log
              .filter((l) => !logFilter || status.tasks.find((t) => t.project_id === logFilter)?.channel === l.channel)
              .map((l, i) => (
                <div key={i}>
                  <span style={{ color: 'var(--text-muted)' }}>{l.at}</span>{' '}
                  <span style={{ color: CHANNEL_COLORS[l.channel] }}>{l.channel}</span>{' '}
                  <span>{l.text}</span>
                </div>
              ))}
            {status.log.length === 0 && <span style={{ color: 'var(--text-muted)' }}>Waiting for the first step…</span>}
          </div>
        </div>
      )}
    </div>
  );
}
