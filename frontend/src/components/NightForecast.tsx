import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Clock, RefreshCw, Route, Wrench, XCircle } from 'lucide-react';
import { getJson, postJson, describeError } from '../services/api';
import { useStudio } from '../state/studio';
import ModelRoutingWindow from './ModelRoutingWindow';

// Tonight's run (2026-10-26): the forecast of the long-form nightly batch,
// the checks that catch a failing night before it starts, and the run live
// against its forecast. Backend: app/services/run_forecast.py.
// The creator: "I can't keep waiting the whole night to find that videos failed in the morning."

interface Step { name: string; job: string; provider: string; model: string; est_min: number; worst_min: number; basis: string }
interface Slot {
  channel: string; slot: number; minutes: number; steps: Step[]; est_min: number; worst_min: number;
  start: string; end: string; worst_end: string; fits: boolean; at_risk: boolean; claude_in: number; claude_out: number;
}
interface Forecast {
  enabled: boolean; start: string; deadline: string; time_limit_hours: number; slots: Slot[];
  total_slots: number; fits_count: number; at_risk_count: number; verdict: string;
  after: { label: string; est_min: number; end: string; fits: boolean };
  claude: { in: number; out: number };
}
interface Check { id: string; label: string; state: 'ok' | 'warn' | 'fail' | 'off'; summary: string; detail: string; fix: string }
interface Preflight { at: string; overall: string; checks: Check[] }
interface LiveTask {
  channel: string; slot: number; stage: string; topic: string | null; detail: string; est_min: number;
  flag: string; step_est_min?: number; step_elapsed_min?: number;
}
interface Live {
  state: string; started_at?: string; updated_at?: string; tasks: LiveTask[]; remaining_min: number; eta: string | null; problems: string[];
}

const PROVIDER: Record<string, string> = { claude: 'Claude', lm_studio: 'Gemma', ollama: 'Ollama', gemini: 'Gemini', llamacpp: 'llama.cpp' };
const COLOR = { ok: '#4ade80', warn: '#f59e0b', fail: '#f87171', off: '#94a3b8' } as const;

function dur(min: number): string {
  const m = Math.round(min);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}`;
}
const hhmm = (iso?: string | null) => (iso ? iso.slice(11, 16) : '—');
const tok = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${Math.round(n / 1000)}k` : String(n));

function StateIcon({ state }: { state: string }) {
  if (state === 'ok') return <CheckCircle2 size={15} color={COLOR.ok} />;
  if (state === 'fail') return <XCircle size={15} color={COLOR.fail} />;
  return <AlertTriangle size={15} color={state === 'warn' ? COLOR.warn : COLOR.off} />;
}

export default function NightForecast() {
  const { toast } = useStudio();
  const [fc, setFc] = useState<Forecast | null>(null);
  const [pf, setPf] = useState<Preflight | null>(null);
  const [live, setLive] = useState<Live | null>(null);
  const [checking, setChecking] = useState(false);
  const [fixing, setFixing] = useState('');
  const [openSlot, setOpenSlot] = useState<string>('');
  const [routing, setRouting] = useState(false);

  const refresh = useCallback(async (fresh = false) => {
    setChecking(true);
    try {
      const [f, p] = await Promise.all([
        getJson<Forecast>('/api/forecast/nightly'),
        getJson<Preflight>(`/api/forecast/preflight${fresh ? '?fresh=1' : ''}`),
      ]);
      setFc(f);
      setPf(p);
    } catch (e) {
      toast(`Could not load tonight's forecast: ${describeError(e)}`, 'error');
    } finally {
      setChecking(false);
    }
  }, [toast]);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    let alive = true;
    const poll = () => getJson<Live>('/api/forecast/live').then((l) => alive && setLive(l)).catch(() => undefined);
    poll();
    const id = window.setInterval(poll, 30_000);
    return () => { alive = false; window.clearInterval(id); };
  }, []);

  const runFix = async (id: string) => {
    setFixing(id);
    try {
      const r = await postJson<{ ok: boolean; message: string }>('/api/forecast/fix', { id });
      toast(r.message, r.ok ? 'success' : 'error');
      await refresh(true);
    } catch (e) {
      toast(`Fix failed: ${describeError(e)}`, 'error');
    } finally {
      setFixing('');
    }
  };

  const muted = { color: 'var(--text-secondary)', fontSize: '0.8rem' } as const;
  const overall = (pf?.overall || 'ok') as keyof typeof COLOR;
  const problems = (pf?.checks || []).filter((c) => c.state === 'fail' || c.state === 'warn');
  const showLive = live && (live.state === 'running' || live.state === 'died'
    || (live.state === 'failed' && live.updated_at && Date.now() - new Date(live.updated_at).getTime() < 18 * 3600_000));

  return (
    <div className="panel-card" style={{ borderLeft: `3px solid ${COLOR[overall] || COLOR.ok}` }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Clock size={20} /> Tonight's run
          {fc && <span style={{ fontSize: '0.8rem', fontWeight: 500, color: 'var(--text-secondary)' }}>
            starts {hhmm(fc.start)} · Windows stops it at {hhmm(fc.deadline)} ({fc.time_limit_hours} h)
          </span>}
        </h3>
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="button" className="btn btn-outline btn-compact" onClick={() => setRouting(true)} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <Route size={14} /> Model routing
          </button>
          <button type="button" className="btn btn-outline btn-compact" disabled={checking} onClick={() => refresh(true)} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <RefreshCw size={14} /> {checking ? 'Checking…' : 'Check now'}
          </button>
        </div>
      </div>

      {fc && <p style={{ margin: '8px 0 0 0', fontSize: '0.9rem' }}>{fc.verdict}{fc.claude.in > 0 && <span style={muted}> · Claude ≈ {tok(fc.claude.in)} in / {tok(fc.claude.out)} out</span>}</p>}

      {showLive && live && (
        <div style={{ marginTop: 12, padding: '10px 12px', borderRadius: 8, border: `1px solid ${live.state === 'running' ? 'var(--border-card)' : COLOR.fail}` }}>
          <div style={{ fontWeight: 600, fontSize: '0.88rem', marginBottom: 6 }}>
            {live.state === 'running' ? `Running now · about ${dur(live.remaining_min)} left, done ≈ ${hhmm(live.eta)}`
              : live.state === 'died' ? `Last run stopped at ${hhmm(live.updated_at)} without finishing`
                : `Last run failed at ${hhmm(live.updated_at)}`}
          </div>
          {live.problems.map((p) => <div key={p} style={{ color: COLOR.fail, fontSize: '0.82rem' }}>• {p}</div>)}
          <div style={{ display: 'grid', gap: 3, marginTop: 6 }}>
            {live.tasks.map((t) => (
              <div key={`${t.channel}-${t.slot}`} style={{ display: 'flex', gap: 10, fontSize: '0.8rem', flexWrap: 'wrap' }}>
                <span style={{ minWidth: 150 }}>{t.channel} #{t.slot}</span>
                <span style={{ minWidth: 150, color: t.flag === 'failed' ? COLOR.fail : t.flag === 'slow' ? COLOR.warn : t.stage === 'done' ? COLOR.ok : 'var(--text-primary)' }}>{t.stage}</span>
                {t.step_elapsed_min !== undefined && <span style={muted}>{dur(t.step_elapsed_min)} of ~{dur(t.step_est_min || 0)}</span>}
                {t.topic && <span style={{ ...muted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 320 }}>{t.topic}</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {problems.length > 0 && (
        <div style={{ display: 'grid', gap: 6, marginTop: 12 }}>
          {problems.map((c) => (
            <div key={c.id} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: '0.84rem' }}>
              <span style={{ marginTop: 2 }}><StateIcon state={c.state} /></span>
              <div style={{ flex: 1 }}>
                <strong>{c.label}:</strong> {c.summary}
                {c.detail && <div style={muted}>{c.detail}</div>}
              </div>
              {c.fix && (
                <button type="button" className="btn btn-compact" disabled={!!fixing} onClick={() => runFix(c.fix)} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <Wrench size={13} /> {fixing === c.fix ? 'Fixing…' : 'Fix'}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
      {pf && problems.length === 0 && <p style={{ ...muted, margin: '8px 0 0 0' }}>All {pf.checks.length} checks pass (checked {hhmm(pf.at)}).</p>}

      {fc && fc.slots.length > 0 && (
        <div style={{ marginTop: 12, display: 'grid', gap: 4 }}>
          {fc.slots.map((s) => {
            const key = `${s.channel}-${s.slot}`;
            const open = openSlot === key;
            const color = !s.fits ? COLOR.fail : s.at_risk ? COLOR.warn : 'var(--text-primary)';
            return (
              <div key={key}>
                <button type="button" onClick={() => setOpenSlot(open ? '' : key)}
                  style={{ display: 'flex', gap: 10, width: '100%', alignItems: 'center', background: 'none', border: 'none', cursor: 'pointer', padding: '3px 0', color, fontSize: '0.82rem', textAlign: 'left' }}>
                  {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                  <span style={{ minWidth: 150 }}>{s.channel} #{s.slot}</span>
                  <span style={{ minWidth: 110 }}>{hhmm(s.start)}–{hhmm(s.end)}</span>
                  <span style={{ minWidth: 150 }}>~{dur(s.est_min)} (slow night {dur(s.worst_min)})</span>
                  <span>{!s.fits ? 'would be cut off' : s.at_risk ? 'at risk' : ''}</span>
                  {s.claude_in > 0 && <span style={{ ...muted, marginLeft: 'auto' }}>Claude {tok(s.claude_in)} / {tok(s.claude_out)}</span>}
                </button>
                {open && (
                  <div style={{ margin: '2px 0 6px 24px', display: 'grid', gap: 2 }}>
                    {s.steps.map((st) => (
                      <div key={st.name} style={{ display: 'flex', gap: 10, fontSize: '0.78rem', flexWrap: 'wrap' }}>
                        <span style={{ minWidth: 170 }}>{st.name}</span>
                        <span style={{ minWidth: 150, color: 'var(--text-secondary)' }}>{PROVIDER[st.provider] || st.provider || '—'}{st.model ? ` · ${st.model}` : ''}</span>
                        <span style={{ minWidth: 120 }}>~{dur(st.est_min)} (≤ {dur(st.worst_min)})</span>
                        <span style={muted}>{st.basis}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
          <div style={{ ...muted, display: 'flex', gap: 10, paddingLeft: 23, color: fc.after.fits ? 'var(--text-secondary)' : COLOR.fail }}>
            <span style={{ minWidth: 150 }}>then</span>
            <span>{fc.after.label}: ~{dur(fc.after.est_min)}, done ≈ {hhmm(fc.after.end)}{fc.after.fits ? '' : ' (after the limit)'}</span>
          </div>
        </div>
      )}

      <ModelRoutingWindow open={routing} onClose={() => { setRouting(false); refresh(); }} />
    </div>
  );
}
