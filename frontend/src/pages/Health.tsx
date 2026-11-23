import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, CircleDashed, RotateCw, ShieldCheck, Wrench, XCircle } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';

// The Health page (2026-10-22): one row per watchdog and service, with its
// real state and the last error in plain words. The point is the silent
// failures: a self-restart check that throws, an idle offload that never
// fires, a model loaded at the wrong context, a nightly task that failed.

interface Diagnostics {
  startup_time_seconds?: number;
  app_name?: string;
  environment?: string;
  log_level?: string;
  loaded_workflows_count?: number;
  registered_agents_count?: number;
  python_version?: string;
  platform?: string;
  [key: string]: unknown;
}

type CheckState = 'ok' | 'warn' | 'fail' | 'off';
interface CheckRow {
  id: string; label: string; state: CheckState | string; summary: string; detail?: string; checked_at?: string;
  app?: string; missing?: string[];
}
interface Checks { at: string; seconds: number; overall: CheckState | string; counts: Record<string, number>; checks: CheckRow[] }

const REFRESH_MS = 60_000;

const STATE_META: Record<string, { colour: string; label: string; icon: React.ReactNode }> = {
  ok: { colour: '#34d399', label: 'OK', icon: <CheckCircle2 size={15} /> },
  warn: { colour: '#f59e0b', label: 'Attention', icon: <AlertTriangle size={15} /> },
  fail: { colour: '#f87171', label: 'Failing', icon: <XCircle size={15} /> },
  off: { colour: '#64748b', label: 'Off', icon: <CircleDashed size={15} /> },
};

function Row({ row }: { row: CheckRow }) {
  const [open, setOpen] = useState(row.state === 'fail');
  const [repairing, setRepairing] = useState(false);
  const [repairNote, setRepairNote] = useState<string | null>(null);
  const meta = STATE_META[row.state] || STATE_META.off;
  // Sibling-app environment rows (2026-10-24) carry `app` and can repair
  // themselves via POST /api/health/app_envs/{app}/repair; a repair is
  // already auto-started for them, this is just "do it again, now".
  const canRepair = row.id.startsWith('app_env_') && row.state !== 'ok' && !!row.app;
  const repair = useCallback(async () => {
    if (!row.app) return;
    setRepairing(true);
    setRepairNote(null);
    try {
      await postJson(`/api/health/app_envs/${encodeURIComponent(row.app)}/repair`);
      setRepairNote('Repair started.');
    } catch (err) {
      setRepairNote(describeError(err));
    } finally {
      setRepairing(false);
    }
  }, [row.app]);
  return (
    <div style={{ borderBottom: '1px solid var(--border-subtle)', padding: '8px 0' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
        <span style={{ color: meta.colour, display: 'inline-flex', marginTop: 2, flexShrink: 0 }} title={meta.label}>{meta.icon}</span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 600, color: 'var(--text-primary)', minWidth: 220 }}>{row.label}</span>
            <span style={{ color: row.state === 'fail' ? '#fca5a5' : row.state === 'warn' ? '#fcd34d' : 'var(--text-secondary)', fontSize: '0.88rem' }}>
              {row.summary}
            </span>
            {canRepair && (
              <button
                type="button"
                className="btn btn-outline"
                onClick={repair}
                disabled={repairing}
                style={{ padding: '2px 10px', fontSize: '0.76rem', display: 'inline-flex', alignItems: 'center', gap: 4 }}
              >
                <Wrench size={12} /> {repairing ? 'Starting…' : 'Repair now'}
              </button>
            )}
            {repairNote && <span style={{ color: 'var(--text-muted)', fontSize: '0.76rem' }}>{repairNote}</span>}
          </div>
          {row.detail && (
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.76rem', padding: '4px 0 0 0', display: 'flex', alignItems: 'center', gap: 4 }}
            >
              {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />} {open ? 'less' : 'details'}
            </button>
          )}
          {open && row.detail && (
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: 4, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{row.detail}</div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function Health() {
  const { health, healthInfo, refreshHealth } = useStudio();
  const [checks, setChecks] = useState<Checks | null>(null);
  const [diag, setDiag] = useState<Diagnostics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showDiag, setShowDiag] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    await refreshHealth();
    try {
      const [c, d] = await Promise.all([
        getJson<Checks>('/api/health/checks', { signal: AbortSignal.timeout(45_000) }),
        getJson<Diagnostics>('/api/diagnostics').catch(() => null),
      ]);
      setChecks(c);
      setDiag(d);
      setError(null);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  }, [refreshHealth]);

  useEffect(() => {
    load();
    const timer = window.setInterval(load, REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [load]);

  const overall = checks?.overall || (health === 'offline' ? 'fail' : 'off');
  const meta = STATE_META[overall] || STATE_META.off;
  const order: Record<string, number> = { fail: 0, warn: 1, ok: 2, off: 3 };
  const rows = [...(checks?.checks || [])].sort((a, b) => (order[a.state] ?? 9) - (order[b.state] ?? 9));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div className="panel-card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
          <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
            <ShieldCheck size={20} /> Health
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: '0.8rem', fontWeight: 700, color: meta.colour, border: `1px solid ${meta.colour}`, borderRadius: 9999, padding: '2px 10px' }}>
              {meta.icon} {health === 'offline' ? 'Backend offline' : meta.label}
            </span>
          </h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            {checks && (
              <span>
                {checks.counts.fail ? <span style={{ color: '#f87171' }}>{checks.counts.fail} failing · </span> : null}
                {checks.counts.warn ? <span style={{ color: '#f59e0b' }}>{checks.counts.warn} need attention · </span> : null}
                {checks.counts.ok} ok · checked {new Date(checks.at).toLocaleTimeString()} in {checks.seconds}s
              </span>
            )}
            <button type="button" className="btn btn-outline" onClick={load} disabled={loading}>
              <RotateCw size={16} />
              <span>{loading ? 'Checking…' : 'Re-check'}</span>
            </button>
          </div>
        </div>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', margin: '8px 0 12px' }}>
          Every watchdog and service with its real state and the last error it hit. A failing row here is a silent failure made loud:
          a self-restart that never applies, models that are never offloaded, a nightly task that stopped, a model loaded with too small a context.
          Refreshes every minute.
        </p>
        {error && <div style={{ color: '#fca5a5', marginBottom: 8 }}>Checks unavailable: {error}</div>}
        {health === 'offline' && <div style={{ color: '#fca5a5' }}>The Studio backend is not answering; nothing below is live.</div>}
        {rows.length === 0 && !error && health !== 'offline' && <div style={{ color: 'var(--text-secondary)' }}>Checking…</div>}
        {rows.map((r) => <Row key={r.id} row={r} />)}
      </div>

      <div className="panel-card" style={{ padding: '12px 20px' }}>
        <button type="button" onClick={() => setShowDiag((v) => !v)} style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.85rem', padding: 0, display: 'flex', alignItems: 'center', gap: 6 }}>
          {showDiag ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Process details
          <span style={{ color: 'var(--text-muted)' }}>
            {healthInfo?.app ? ` · ${healthInfo.app} v${healthInfo.version || '?'}` : ''}
            {diag?.startup_time_seconds !== undefined ? ` · up ${Math.round(Number(diag.startup_time_seconds) / 60)} min` : ''}
          </span>
        </button>
        {showDiag && diag && (
          <div className="logs-panel" style={{ marginTop: 10, color: '#38bdf8' }}>
            {[
              ['Application', `${diag.app_name || '—'} (${diag.environment || '—'})`],
              ['Uptime', diag.startup_time_seconds !== undefined ? `${Math.round(Number(diag.startup_time_seconds))} s` : '—'],
              ['Workflows loaded', String(diag.loaded_workflows_count ?? '—')],
              ['Agents registered', String(diag.registered_agents_count ?? '—')],
              ['Log level', String(diag.log_level ?? '—')],
              ['Python', String(diag.python_version ?? '—')],
              ['Platform', String(diag.platform ?? '—')],
              ['Port / pid', `${healthInfo?.port ?? '—'} / ${healthInfo?.pid ?? '—'}`],
            ].map(([k, v]) => (
              <div key={k} style={{ display: 'flex', gap: 12 }}>
                <span style={{ color: '#64748b', minWidth: 200 }}>{k}</span>
                <span>{v}</span>
              </div>
            ))}
          </div>
        )}
        <p style={{ color: '#94a3b8', fontSize: '0.8rem', marginTop: 10, marginBottom: 0 }}>
          The desktop app logs to backend/logs/studio.log. Run <code>python backend/preflight.py</code> for the launch checks.
        </p>
      </div>
    </div>
  );
}
