import { useCallback, useEffect, useState } from 'react';
import { Pause, PauseCircle, Play } from 'lucide-react';
import { getJson, postJson, describeError } from '../services/api';

// The master pause / resume (docs/STUDIO_DIRECTOR_PLAN.md Part 1): one
// switch for the whole Studio + BuzzEdit + the model servers. `MasterBadge`
// is the small header control; `MasterPanel` is the fuller Dashboard card.

export interface MasterState {
  paused: boolean;
  since: string | null;
  reason: string;
  mode: 'soft' | 'now';
  by?: string;
  held: string[];
  ram_free_mb?: number | null;
  vram_free_mb?: number | null;
  vram_total_mb?: number | null;
  loaded_models?: { lm_studio?: string[]; ollama?: string[] };
  buzzedit?: { paused?: boolean; held?: string[] } | null;
}

const POLL_MS = 15_000;

function useMasterState() {
  const [state, setState] = useState<MasterState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(() => {
    return getJson<MasterState>('/api/master/state')
      .then((s) => { setState(s); setError(null); })
      .catch((e) => setError(describeError(e)));
  }, []);
  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);
  return { state, error, refresh };
}

async function pauseNow(mode: 'soft' | 'now', reason: string, by: string) {
  return postJson('/api/master/pause', { mode, reason, by });
}
async function resumeNow() {
  return postJson('/api/master/resume', {});
}

export function MasterBadge() {
  const { state, refresh } = useMasterState();
  const [busy, setBusy] = useState(false);
  if (!state) return null;
  const onClick = async () => {
    setBusy(true);
    try {
      if (state.paused) await resumeNow();
      else await pauseNow('soft', 'Paused from the header', 'Dashboard');
      await refresh();
    } finally {
      setBusy(false);
    }
  };
  return (
    <button
      type="button"
      className="status-badge"
      onClick={onClick}
      disabled={busy}
      title={state.paused
        ? `Master paused since ${state.since || '?'}${state.by ? ` by ${state.by}` : ''}${state.reason ? `: ${state.reason}` : ''}. Click to resume.`
        : 'Everything is running. Click to pause.'}
      style={{
        display: 'flex', alignItems: 'center', gap: 7, cursor: 'pointer', border: 'none',
        background: state.paused ? 'rgba(245,158,11,0.15)' : 'transparent',
      }}
    >
      <div className="status-dot" style={{ backgroundColor: state.paused ? '#f59e0b' : '#4ade80' }} />
      <span className="status-badge-text">
        {state.paused ? `Paused${state.held.length ? ` (${state.held.length} held)` : ''}` : 'Running'}
      </span>
    </button>
  );
}

export function MasterPanel() {
  const { state, error, refresh } = useMasterState();
  const [mode, setMode] = useState<'soft' | 'now'>('soft');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const onPause = async () => {
    setBusy(true);
    try {
      await pauseNow(mode, reason || 'Paused from the Dashboard', 'Dashboard');
      await refresh();
    } finally {
      setBusy(false);
    }
  };
  const onResume = async () => {
    setBusy(true);
    try {
      await resumeNow();
      await refresh();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="panel-card" style={{ borderLeft: `3px solid ${state?.paused ? '#f59e0b' : '#4ade80'}` }}>
      <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
        <PauseCircle size={20} /> Master pause
      </h3>
      {error && <div style={{ color: '#f87171', fontSize: '0.85rem', marginTop: 8 }}>{error}</div>}
      {state && (
        <div style={{ marginTop: 10 }}>
          <div style={{ fontSize: '0.95rem', color: 'var(--text-primary)' }}>
            {state.paused
              ? `Paused since ${state.since || '?'} (${state.mode} mode)${state.by ? ` by ${state.by}` : ''}${state.reason ? ` -- ${state.reason}` : ''}`
              : 'Everything is running.'}
          </div>
          {state.paused && (
            <div style={{ marginTop: 6, fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
              Held at: {state.held.length ? state.held.join(', ') : 'nothing yet -- the current step is finishing first'}
            </div>
          )}
          <div style={{ marginTop: 10, fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
            RAM free: {state.ram_free_mb != null ? `${Math.round(state.ram_free_mb).toLocaleString()} MB` : '—'}
            {' · '}VRAM free: {state.vram_free_mb != null ? `${Math.round(state.vram_free_mb).toLocaleString()} MB` : '—'}
            {state.vram_total_mb != null ? ` / ${Math.round(state.vram_total_mb).toLocaleString()} MB` : ''}
          </div>
          <div style={{ marginTop: 14, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            {!state.paused ? (
              <>
                <select
                  className="form-control"
                  aria-label="Pause mode"
                  style={{ width: 220 }}
                  value={mode}
                  onChange={(e) => setMode(e.target.value as 'soft' | 'now')}
                >
                  <option value="soft">Soft -- finish the current step</option>
                  <option value="now">Now -- also interrupt the render</option>
                </select>
                <input
                  className="form-control"
                  aria-label="Pause reason"
                  style={{ flex: 1, minWidth: 160 }}
                  placeholder="Reason (optional)"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
                <button type="button" className="btn" disabled={busy} onClick={onPause}>
                  <Pause size={16} /><span>Pause everything</span>
                </button>
              </>
            ) : (
              <button type="button" className="btn" disabled={busy} onClick={onResume}>
                <Play size={16} /><span>Resume</span>
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
