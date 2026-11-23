import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ArrowDown,
  ArrowUp,
  FolderOpen,
  ListVideo,
  Pause,
  Plus,
  Play,
  RefreshCw,
  RotateCcw,
  Trash2,
  X,
} from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';
import type { ProduceQueue, ProduceQueueItem, ProduceQueueStageTime } from '../lib/types';
import AddVideosDialog from './AddVideosDialog';

// The video-production queue (app/services/produce_queue.py): every channel's
// videos, one at a time on the GPU. Pause/resume stop a run at its next safe
// point (after import, transcription, or visual planning) and pick it back up
// there; a BuzzEdit render itself cannot be paused, so the queue-level pause
// is what holds the next video.

const STATUS_STYLE: Record<ProduceQueueItem['status'], { label: string; color: string }> = {
  queued: { label: 'Queued', color: '#38bdf8' },
  running: { label: 'Running', color: '#f59e0b' },
  paused: { label: 'Paused', color: '#a78bfa' },
  awaiting_review: { label: 'Needs review', color: '#f59e0b' },
  done: { label: 'Done', color: '#34d399' },
  failed: { label: 'Failed', color: '#ef4444' },
  cancelled: { label: 'Cancelled', color: '#64748b' },
};

const STAGE_LABEL: Record<string, string> = {
  start: 'import',
  transcribe: 'transcription & cut',
  plan: 'visual planning',
  finalize: 'render hand-off',
  render: 'render',
};

const STAGE_ORDER = ['start', 'transcribe', 'plan', 'finalize', 'render'];

function formatDuration(totalSeconds: number): string {
  const t = Math.max(0, Math.round(totalSeconds));
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const sec = t % 60;
  if (h) return `${h}h ${String(m).padStart(2, '0')}m ${String(sec).padStart(2, '0')}s`;
  if (m) return `${m}m ${String(sec).padStart(2, '0')}s`;
  return `${sec}s`;
}

function entrySeconds(entry: ProduceQueueStageTime, now: number): number {
  if (entry.seconds != null) return entry.seconds;
  if (!entry.finished_at) return (now - new Date(entry.started_at).getTime()) / 1000;
  return 0; // interrupted with no end time
}

// Time spent in each stage of one queue item, summed across attempts, with the
// running stage ticking live.
function StageTimes({ entries }: { entries: ProduceQueueStageTime[] }) {
  const running = entries.some((e) => !e.finished_at);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return undefined;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [running]);

  const rows = STAGE_ORDER.map((stage) => {
    const mine = entries.filter((e) => e.stage === stage);
    if (!mine.length) return null;
    const last = mine[mine.length - 1];
    return {
      stage,
      seconds: mine.reduce((sum, e) => sum + entrySeconds(e, now), 0),
      runs: mine.length,
      live: !last.finished_at,
      outcome: last.outcome,
    };
  }).filter((r): r is NonNullable<typeof r> => r !== null);
  const total = rows.reduce((sum, r) => sum + r.seconds, 0);

  return (
    <details style={{ marginTop: 6, fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
      <summary style={{ cursor: 'pointer', userSelect: 'none' }}>
        Stage times — {formatDuration(total)}{running ? ' so far' : ''}
      </summary>
      <table style={{ marginTop: 4, borderCollapse: 'collapse' }}>
        <tbody>
          {rows.map((r) => (
            <tr key={r.stage}>
              <td style={{ padding: '1px 12px 1px 0', textTransform: 'capitalize' }}>{STAGE_LABEL[r.stage] || r.stage}</td>
              <td style={{ padding: '1px 12px 1px 0', fontVariantNumeric: 'tabular-nums', textAlign: 'right' }}>
                {formatDuration(r.seconds)}
              </td>
              <td style={{ padding: '1px 0', color: r.live ? '#f59e0b' : 'var(--text-muted)' }}>
                {r.live ? 'running' : r.outcome && r.outcome !== 'done' ? r.outcome.replace('_', ' ') : ''}
                {r.runs > 1 ? ` (${r.runs} runs)` : ''}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

type Action = 'pause' | 'resume' | 'cancel' | 'retry' | 'restart' | 'move' | 'remove';

export default function ProductionQueue({
  refreshKey,
  onChange,
  onOpenProject,
}: {
  // Bump to refetch now (e.g. right after a video was queued elsewhere).
  refreshKey?: number;
  // Called whenever a fetch or an action returns a new queue.
  onChange?: (queue: ProduceQueue) => void;
  onOpenProject?: (projectId: string) => void;
}) {
  const { toast, confirm } = useStudio();
  const [queue, setQueue] = useState<ProduceQueue | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [adding, setAdding] = useState(false);
  const timer = useRef<number | null>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const apply = useCallback((q: ProduceQueue) => {
    setQueue(q);
    onChangeRef.current?.(q);
  }, []);

  const load = useCallback(async () => {
    try {
      apply(await getJson<ProduceQueue>('/api/produce/queue'));
    } catch {
      // keep what we had; the next tick tries again
    }
  }, [apply]);

  const live = !!queue?.items.some((i) => i.status === 'running' || i.status === 'queued');

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  // Poll fast while something is moving, slowly otherwise.
  useEffect(() => {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = window.setInterval(() => void load(), live ? 3000 : 15000);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [live, load]);

  const act = async (item: ProduceQueueItem, action: Action, body?: Record<string, unknown>) => {
    if (action === 'cancel' || action === 'restart') {
      const ok = await confirm({
        title: action === 'cancel' ? `Cancel "${item.title}"?` : `Restart "${item.title}" from scratch?`,
        body: action === 'cancel'
          ? item.status === 'running' && item.checkpoint === 'render'
            ? 'BuzzEdit cannot abort a clip mid-render: the Studio stops tracking it and moves on, but BuzzEdit may finish the render in the background.'
            : item.status === 'running'
              ? 'The run stops at its next safe point (after the current stage finishes). You can retry it later from there.'
              : 'It leaves the queue. You can retry it later.'
          : 'The recording is imported and transcribed again, and visuals are re-planned. Any earlier progress for this video is discarded.',
        confirmLabel: action === 'cancel' ? 'Cancel video' : 'Restart',
        danger: true,
      });
      if (!ok) return;
    }
    setBusy(`${item.id}:${action}`);
    try {
      apply(await postJson<ProduceQueue>(`/api/produce/queue/${encodeURIComponent(item.id)}/${action}`, body || {}));
      if (action === 'pause' && item.status === 'running') {
        toast(`"${item.title}" will pause after its current stage.`, 'info');
      }
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setBusy(null);
    }
  };

  const setPaused = async (paused: boolean) => {
    setBusy('queue');
    try {
      apply(await postJson<ProduceQueue>('/api/produce/queue/paused', { paused }));
      toast(paused ? 'Queue paused: the current video finishes, nothing new starts.' : 'Queue resumed.', 'info');
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setBusy(null);
    }
  };

  const clearFinished = async () => {
    setBusy('clear');
    try {
      apply(await postJson<ProduceQueue>('/api/produce/queue/clear_finished', {}));
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setBusy(null);
    }
  };

  if (!queue) return null;

  const activeProjectIds = new Set(queue.items
    .filter((i) => ['queued', 'running', 'paused', 'awaiting_review'].includes(i.status))
    .map((i) => i.project_id));
  const addDialog = (
    <AddVideosDialog open={adding} onClose={() => setAdding(false)} onQueued={apply} activeProjectIds={activeProjectIds} />
  );
  const addBtn = (
    <button
      type="button"
      className="btn btn-outline btn-sm"
      onClick={() => setAdding(true)}
      title="Queue several videos of one channel at once: new recordings or existing projects."
      style={{ padding: '3px 10px', fontSize: '0.74rem' }}
    >
      <Plus size={12} />
      <span>Add videos</span>
    </button>
  );

  if (queue.items.length === 0) {
    return (
      <div className="stages-glimpse-container" style={{ marginBottom: 18 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <ListVideo size={15} style={{ color: 'var(--accent-primary)' }} />
          <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>Production queue</span>
          <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>empty</span>
          <div style={{ marginLeft: 'auto' }}>{addBtn}</div>
        </div>
        {addDialog}
      </div>
    );
  }

  const counts = queue.items.reduce<Record<string, number>>((acc, i) => {
    acc[i.status] = (acc[i.status] || 0) + 1;
    return acc;
  }, {});
  const hasFinished = (counts.done || 0) + (counts.cancelled || 0) > 0;
  const waitingIds = queue.items.filter((i) => i.status !== 'running').map((i) => i.id);

  const btn = (item: ProduceQueueItem, action: Action, label: string, Icon: typeof Play, title: string,
    body?: Record<string, unknown>, disabled = false) => (
    <button
      type="button"
      className="btn btn-outline btn-sm"
      disabled={disabled || busy !== null}
      onClick={(e) => {
        e.stopPropagation();
        void act(item, action, body);
      }}
      title={title}
      aria-label={label ? undefined : title}
      style={{ padding: '2px 8px', fontSize: '0.72rem' }}
    >
      <Icon size={11} />
      {label && <span>{label}</span>}
    </button>
  );

  return (
    <div className="stages-glimpse-container" style={{ marginBottom: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 8, color: 'var(--text-primary)' }}
        >
          <ListVideo size={15} style={{ color: 'var(--accent-primary)' }} />
          <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>Production queue</span>
        </button>
        <span style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>
          {[
            counts.running && `${counts.running} running`,
            counts.queued && `${counts.queued} queued`,
            counts.paused && `${counts.paused} paused`,
            counts.awaiting_review && `${counts.awaiting_review} need review`,
            counts.failed && `${counts.failed} failed`,
            counts.done && `${counts.done} done`,
          ].filter(Boolean).join(' · ')}
        </span>
        {queue.paused && (
          <span style={{ fontSize: '0.72rem', padding: '2px 8px', borderRadius: 12, color: '#a78bfa', border: '1px solid rgba(167, 139, 250, 0.35)', background: 'rgba(167, 139, 250, 0.1)' }}>
            Queue paused
          </span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {addBtn}
          <button
            type="button"
            className="btn btn-outline btn-sm"
            disabled={busy !== null}
            onClick={() => void setPaused(!queue.paused)}
            title={queue.paused ? 'Start the next queued video when the GPU is free.'
              : 'Hold the queue: the video in progress finishes, nothing new starts.'}
            style={{ padding: '3px 10px', fontSize: '0.74rem' }}
          >
            {queue.paused ? <Play size={12} /> : <Pause size={12} />}
            <span>{queue.paused ? 'Resume queue' : 'Pause queue'}</span>
          </button>
          {hasFinished && (
            <button
              type="button"
              className="btn btn-outline btn-sm"
              disabled={busy !== null}
              onClick={() => void clearFinished()}
              title="Remove done and cancelled videos from the list (failed ones stay so you can retry them)."
              style={{ padding: '3px 10px', fontSize: '0.74rem' }}
            >
              <Trash2 size={12} />
              <span>Clear finished</span>
            </button>
          )}
        </div>
      </div>

      {!collapsed && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 12 }}>
          {queue.items.map((item) => {
            const st = STATUS_STYLE[item.status];
            const running = item.status === 'running';
            const rendering = running && item.checkpoint === 'render';
            const pos = waitingIds.indexOf(item.id);
            const progress = item.status === 'done' ? 1 : item.progress ?? null;
            let detail: string | null = null;
            if (running) {
              detail = item.cancel_requested ? 'Cancelling after the current stage…'
                : item.pause_requested ? 'Pausing after the current stage…'
                : item.message || 'Working…';
            } else if (item.status === 'paused') {
              // The server's wording, shared with the project panel's status.
              detail = item.message || `Resumes at ${STAGE_LABEL[item.resume_from] || item.resume_from}.`;
            } else if (item.status === 'queued') {
              detail = item.message || (item.resume_from !== 'start' ? `Waiting — picks up at ${STAGE_LABEL[item.resume_from] || item.resume_from}.` : 'Waiting for its turn.');
            } else if (item.status === 'awaiting_review') {
              detail = item.message || 'Waiting for your review in the project panel.';
            } else if (item.status === 'failed') {
              detail = item.error || 'Failed.';
            }
            return (
              <div
                key={item.id}
                style={{
                  padding: '8px 10px',
                  borderRadius: 6,
                  border: `1px solid ${running ? 'rgba(245, 158, 11, 0.35)' : 'var(--border-color, rgba(255,255,255,0.1))'}`,
                  background: running ? 'rgba(245, 158, 11, 0.05)' : undefined,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: '0.7rem', fontWeight: 600, color: st.color, minWidth: 82 }}>
                    ● {st.label}
                  </span>
                  <span className="brand-badge">{item.brand}</span>
                  <button
                    type="button"
                    onClick={() => onOpenProject?.(item.project_id)}
                    title="Open this project"
                    style={{ background: 'none', border: 'none', padding: 0, cursor: onOpenProject ? 'pointer' : 'default', color: 'var(--text-primary)', fontSize: '0.82rem', fontWeight: 500, textAlign: 'left', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 380 }}
                  >
                    {item.title}
                  </button>
                  {item.attempts > 1 && (
                    <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>attempt {item.attempts}</span>
                  )}
                  <div style={{ marginLeft: 'auto', display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {item.status === 'queued' && btn(item, 'pause', 'Pause', Pause, 'Hold this video in the queue.')}
                    {running && !rendering && !item.pause_requested
                      && btn(item, 'pause', 'Pause', Pause, 'Pause after the current stage; resume picks up from there.')}
                    {running && rendering && (
                      <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', alignSelf: 'center' }}
                        title="BuzzEdit cannot suspend a render. Pause the queue to hold the next video.">
                        rendering in BuzzEdit
                      </span>
                    )}
                    {(item.status === 'paused' || (running && item.pause_requested))
                      && btn(item, 'resume', 'Resume', Play, running ? 'Keep going instead of pausing.' : 'Put it back in the queue.')}
                    {item.status === 'awaiting_review' && !(item.stage_state && !item.stage_state.startsWith('awaiting')) && (
                      <button
                        type="button"
                        className="btn btn-sm"
                        title="Open this project at the step waiting for your review."
                        style={{ display: 'inline-flex', alignItems: 'center', gap: 4, background: 'rgba(245, 158, 11, 0.18)', fontWeight: 600 }}
                        onClick={() => {
                          onOpenProject?.(item.project_id);
                          window.setTimeout(() => {
                            document.querySelector(`[data-project-id="${item.project_id}"]`)
                              ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
                          }, 200);
                        }}
                      >
                        <Play size={12} /> Review
                      </button>
                    )}
                    {item.status === 'failed' && btn(item, 'retry', 'Retry', RotateCcw,
                      `Retry from the last safe point (${STAGE_LABEL[item.checkpoint || 'start'] || 'import'}).`)}
                    {(item.status === 'cancelled') && btn(item, 'retry', 'Retry', RotateCcw,
                      `Queue it again from ${STAGE_LABEL[item.checkpoint || 'start'] || 'import'}.`)}
                    {(item.status === 'failed' || item.status === 'cancelled' || item.status === 'paused' || item.status === 'done')
                      && item.recording_path
                      && btn(item, 'restart', 'Restart', RefreshCw, 'Start over: re-import and re-transcribe the recording.')}
                    {!running && item.status !== 'done' && item.status !== 'failed' && item.status !== 'cancelled' && (
                      <>
                        {btn(item, 'move', '', ArrowUp, 'Move up', { direction: 'up' }, pos <= 0)}
                        {btn(item, 'move', '', ArrowDown, 'Move down', { direction: 'down' }, pos < 0 || pos >= waitingIds.length - 1)}
                      </>
                    )}
                    {item.status !== 'done' && item.status !== 'failed' && item.status !== 'cancelled' && !item.cancel_requested
                      && btn(item, 'cancel', '', X, 'Cancel this video.')}
                    {!running && (item.status === 'done' || item.status === 'failed' || item.status === 'cancelled')
                      && btn(item, 'remove', '', Trash2, 'Remove from the list.')}
                  </div>
                </div>
                {(running || item.status === 'awaiting_review') && progress !== null && (
                  <div className="stages-progress-bar-bg" style={{ marginTop: 6 }}>
                    <div
                      className="stages-progress-bar-fill"
                      style={{ width: `${Math.round(progress * 100)}%`, background: 'linear-gradient(90deg, #10b981, #3b82f6, #a78bfa)' }}
                    />
                  </div>
                )}
                {detail && (
                  <div style={{ fontSize: '0.74rem', marginTop: 4, color: item.status === 'failed' ? '#f87171' : 'var(--text-secondary)', overflowWrap: 'anywhere' }}>
                    {detail}
                  </div>
                )}
                {item.status === 'done' && item.final_output_path && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4, fontSize: '0.74rem', color: 'var(--text-secondary)', overflowWrap: 'anywhere' }}>
                    <span>Final video: <strong style={{ color: 'var(--text-primary)' }}>{item.final_output_path.split(/[\\/]/).pop()}</strong></span>
                    <button
                      type="button"
                      className="btn btn-sm"
                      title={item.final_output_path}
                      onClick={() => postJson(`/api/projects/${encodeURIComponent(item.project_id)}/produce_video/reveal`, {})
                        .catch((err) => toast(describeError(err), 'error'))}
                      style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}
                    >
                      <FolderOpen size={12} /> Open in Explorer
                    </button>
                  </div>
                )}
                {!!item.stage_times?.length && <StageTimes entries={item.stage_times} />}
              </div>
            );
          })}
        </div>
      )}
      {addDialog}
    </div>
  );
}
