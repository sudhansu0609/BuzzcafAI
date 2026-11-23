import { useCallback, useEffect, useRef, useState } from 'react';
import { Moon, Play, RotateCw, Save } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, putJson, describeError } from '../services/api';
import type { ChannelFormatDefaults, ChannelFormatsState } from '../lib/types';
import NightlyControls, { type NightlyState } from './NightlyControls';

// The long-form half of the nightly run (backend app/services/longform_nightly.py).
// Per channel, the channel strategist plans the video with every Studio tool and
// agent, following the creator's instructions below; research and script then
// run on that plan and stop at Visual Plan for review. The live status comes
// from a file the run rewrites as it goes, so a 03:00 run shows here too.
// Lives on the Scheduler Desk's Long form tab, with its own wake time, hibernate
// and idle settings (its own Windows task; the Shorts tab has another).

type Task = { channel: string; slot: number; stage: string; topic: string | null; project_id: string | null; detail: string; minutes?: number | null };
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

function estimateTaskRemaining(stage: string, minutes?: number | null): string | null {
  if (stage === 'done' || stage === 'failed' || stage === 'queued' || stage === 'skipped') return null;
  const s = stage.toLowerCase();
  if (s.includes('plan') || s.includes('strat')) return '~1-2 min';
  if (s.includes('research')) return '~3-5 min';
  if (s.includes('script') || s.includes('story')) {
    const mins = minutes || 20;
    return `~${Math.max(5, Math.round(mins * 0.7))} min`;
  }
  if (s.includes('visual')) return '~2-3 min';
  if (s.includes('narration') || s.includes('human')) return '~4-7 min';
  if (s.includes('seo')) return '~3-5 min';
  if (s.includes('render')) return '~5-10 min';
  return '~2-4 min';
}

export default function LongformScheduler({ onOpenProject }: { onOpenProject: (id: string) => void }) {
  const { toast, refreshProjects, channelFilter } = useStudio();
  const [state, setState] = useState<LongformState | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [logFilter, setLogFilter] = useState<string | null>(null);
  const [showRules, setShowRules] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  // Every long video of a channel: Shorts first or not, how many, the face
  // layout, and (Raat3Baje) the next episode's format.
  const [formats, setFormats] = useState<ChannelFormatsState | null>(null);

  const load = useCallback(() => {
    getJson<LongformState>('/api/longform/nightly').then(setState).catch(() => undefined);
    getJson<ChannelFormatsState>('/api/channel_formats').then(setFormats).catch(() => undefined);
  }, []);
  useEffect(load, [load]);

  const saveFormat = async (channel: string, patch: Partial<ChannelFormatDefaults> & { next_format?: string | null; lock_format?: string | null }) => {
    try {
      setFormats(await putJson<ChannelFormatsState>(`/api/channel_formats/${encodeURIComponent(channel)}`, patch));
    } catch (e) {
      toast(describeError(e), 'error');
    }
  };

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
            onChange={(e) => save({ per_channel: Math.max(1, Math.min(5, Number(e.target.value) || 1)) })} aria-label="Per channel" style={{ width: 60 }} />
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
                  <input type="checkbox" checked={state.channels.includes(ch)} onChange={(e) => toggleChannel(ch, e.target.checked)} aria-label={`${ch} enabled`} style={{ width: 16, height: 16 }} />
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
              {(() => {
                const d = formats?.channels[ch];
                if (!d) return null;
                const episodeFormats = formats?.episode_formats[ch];
                const nextKey = formats?.next_format[ch];
                const pinned = formats?.pinned_format[ch] || '';
                const locked = formats?.locked_format?.[ch] || '';
                const faceButton = (value: 'mixed' | 'face_intro', label: string) => (
                  <button type="button" className={`btn btn-sm${d.face_layout === value ? '' : ' btn-outline'}`}
                    onClick={() => saveFormat(ch, { face_layout: value })}
                    style={{ padding: '1px 8px', fontSize: '0.74rem', height: 24, borderRadius: 0 }}>
                    {label}
                  </button>
                );
                return (
                  <div style={{ display: 'grid', gap: 6, margin: '8px 0', fontSize: '0.8rem' }}>
                    <span style={{ fontWeight: 600 }}>Every long video</span>
                    <label style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', cursor: 'pointer' }}
                      title="You record the Shorts at the start of the session, then the long video. The Shorts Scripts step writes them; production splits the recording at your greeting and makes each Short its own project. A project can still choose otherwise.">
                      <input type="checkbox" checked={d.shorts_first} onChange={(e) => saveFormat(ch, { shorts_first: e.target.checked })}
                        aria-label={`${ch} record Shorts first`}
                        style={{ width: 16, height: 16 }} />
                      Record
                      <select className="form-control" value={d.shorts_count} disabled={!d.shorts_first}
                        onChange={(e) => saveFormat(ch, { shorts_count: Number(e.target.value) })}
                        aria-label={`${ch} Shorts count`}
                        style={{ width: 'auto', padding: '1px 6px', height: 24, fontSize: '0.78rem' }}>
                        <option value={3}>3</option>
                        <option value={4}>4</option>
                      </select>
                      Shorts first, then the long video
                    </label>
                    <span style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}
                      title="Mixed: your face comes back between the pictures all through. Face first: only your face for the opening, then pictures and clips only. A project can still choose otherwise.">
                      Face:
                      <span style={{ display: 'inline-flex', borderRadius: 6, overflow: 'hidden' }}>
                        {faceButton('mixed', 'Mixed')}{faceButton('face_intro', 'Face first')}
                      </span>
                      {d.face_layout === 'face_intro' && (
                        <>
                          <select className="form-control" value={d.face_intro_seconds}
                            onChange={(e) => saveFormat(ch, { face_intro_seconds: Number(e.target.value) })}
                            aria-label={`${ch} face intro length`}
                            style={{ width: 'auto', padding: '1px 6px', height: 24, fontSize: '0.78rem' }}>
                            {[30, 45, 60, 75, 90, 105, 120, 150, 180].map((s) => (
                              <option key={s} value={s}>{s < 60 ? `${s} s` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')} min`}</option>
                            ))}
                          </select>
                          then pictures only
                        </>
                      )}
                    </span>
                    {episodeFormats && episodeFormats.length > 0 && (
                      <label style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}
                        title="The story format of the next nightly episode. Picking one here uses it once, then the channel's rotation carries on from it. Tick Every episode to lock the chosen format for all of them.">
                        Next episode:
                        <select className="form-control" value={locked || pinned}
                          onChange={(e) => (locked
                            ? saveFormat(ch, { lock_format: e.target.value || null })
                            : saveFormat(ch, { next_format: e.target.value || null }))}
                          aria-label={`${ch} next episode format`}
                          style={{ width: 'auto', padding: '1px 6px', height: 24, fontSize: '0.78rem' }}>
                          <option value="">In turn ({episodeFormats.find((f) => f.key === (pinned ? null : nextKey))?.label ?? 'rotation'})</option>
                          {episodeFormats.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
                        </select>
                        <label style={{ display: 'inline-flex', gap: 4, alignItems: 'center', cursor: 'pointer' }}>
                          <input type="checkbox" checked={!!locked}
                            onChange={(e) => saveFormat(ch, { lock_format: e.target.checked ? (pinned || nextKey || null) : null })}
                            aria-label={`${ch} lock format for every episode`}
                            style={{ width: 16, height: 16 }} />
                          Every episode
                        </label>
                      </label>
                    )}
                  </div>
                );
              })()}
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
                aria-label={`${ch} instructions`}
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
                {typeof t.minutes === 'number' && (
                  <span style={{ color: 'var(--text-secondary)', fontSize: '0.78rem' }}>{t.minutes} min</span>
                )}
                {estimateTaskRemaining(t.stage, t.minutes) && (
                  <span style={{
                    color: '#c084fc',
                    background: 'rgba(192, 132, 252, 0.12)',
                    border: '1px solid rgba(192, 132, 252, 0.28)',
                    borderRadius: 4,
                    padding: '1px 6px',
                    fontSize: '0.74rem',
                    fontWeight: 600,
                  }}>
                    ⏳ {estimateTaskRemaining(t.stage, t.minutes)} remaining
                  </span>
                )}
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
