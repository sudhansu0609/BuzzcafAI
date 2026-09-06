import { useCallback, useEffect, useState } from 'react';
import { RotateCw, ShieldCheck } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, describeError } from '../services/api';

interface Diagnostics {
  startup_time_seconds?: number;
  app_name?: string;
  environment?: string;
  log_level?: string;
  loaded_workflows_count?: number;
  loaded_workflows?: string[];
  registered_agents_count?: number;
  python_version?: string;
  platform?: string;
  [key: string]: unknown;
}

export default function Health() {
  const { health, healthInfo, refreshHealth } = useStudio();
  const [diag, setDiag] = useState<Diagnostics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    await refreshHealth();
    try {
      setDiag(await getJson<Diagnostics>('/api/diagnostics'));
      setError(null);
    } catch (err) {
      setDiag(null);
      setError(describeError(err));
    } finally {
      setLoading(false);
    }
  }, [refreshHealth]);

  useEffect(() => {
    load();
  }, [load]);

  const row = (label: string, value: unknown) => (
    <div key={label} style={{ display: 'flex', gap: 12 }}>
      <span style={{ color: '#64748b', minWidth: 200 }}>{label}</span>
      <span>{value === undefined || value === null ? '—' : String(value)}</span>
    </div>
  );

  return (
    <div className="panel-card">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 12 }}>
        <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0 }}><ShieldCheck size={20} /> System diagnostics</h3>
        <button type="button" className="btn btn-outline" onClick={load} disabled={loading}>
          <RotateCw size={16} />
          <span>{loading ? 'Checking…' : 'Re-check'}</span>
        </button>
      </div>
      <div className="logs-panel" style={{ minHeight: 220, color: health === 'online' ? '#38bdf8' : '#fca5a5' }}>
        {row('Backend', health === 'online' ? `online (${healthInfo?.app || 'unknown app'} v${healthInfo?.version || '?'})` : health === 'offline' ? 'offline' : 'checking…')}
        {error && <div style={{ color: '#fca5a5' }}>Diagnostics unavailable: {error}</div>}
        {diag && (
          <>
            {row('Application', `${diag.app_name || '—'} (${diag.environment || '—'})`)}
            {row('Uptime', diag.startup_time_seconds !== undefined ? `${Math.round(Number(diag.startup_time_seconds))} s` : undefined)}
            {row('Workflows loaded', diag.loaded_workflows_count)}
            {row('Workflow ids', (diag.loaded_workflows || []).join(', '))}
            {row('Agents registered', diag.registered_agents_count)}
            {row('Log level', diag.log_level)}
            {row('Python', diag.python_version)}
            {row('Platform', diag.platform)}
          </>
        )}
      </div>
      <p style={{ color: '#94a3b8', fontSize: '0.85rem', marginTop: 12 }}>
        The desktop app logs to backend/logs/studio.log. Run <code>python backend/preflight.py</code> for the launch checks.
      </p>
    </div>
  );
}
