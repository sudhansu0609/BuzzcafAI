import { useEffect, useState } from 'react';
import { Route, X, Save } from 'lucide-react';
import { getJson, putJson, describeError } from '../services/api';
import { useStudio } from '../state/studio';

// Model Routing (2026-10-26): which model does each kind of work -- Claude,
// Gemma (LM Studio), Ollama or Gemini -- and what it falls back to. Backend:
// integrations/llm.py `job_routes`, app/api/forecast_api.py.

type Provider = '' | 'claude' | 'lm_studio' | 'ollama' | 'gemini';

interface Measured { in: number; out: number; s: number; calls: number }

interface RouteEntry { provider: Provider; model: string; fallback: Provider }

interface JobRoute {
  key: string;
  label: string;
  day: RouteEntry;
  night: RouteEntry;
  measured: Record<string, Measured>;
}

type Profile = 'day' | 'night';

interface RoutesResponse {
  jobs: JobRoute[];
  night_hours: { start: string; end: string };
  profile_now: Profile;
  claude_models: string[];
  gemma_model: string;
  ollama_models: string[];
  gemini_model: string;
  claude_ready: boolean;
}

interface ForecastTokens { claude: { in: number; out: number }; verdict: string }

const PROVIDERS: { id: Provider; label: string }[] = [
  { id: '', label: 'Auto' },
  { id: 'claude', label: 'Claude' },
  { id: 'lm_studio', label: 'Gemma' },
  { id: 'ollama', label: 'Ollama' },
  { id: 'gemini', label: 'Gemini' },
];

const PROVIDER_NAME: Record<string, string> = { claude: 'Claude', lm_studio: 'Gemma', ollama: 'Ollama', gemini: 'Gemini', llamacpp: 'llama.cpp' };

const HINT: Record<string, string> = {
  research: 'Web research loop: the most input tokens of any job.',
  script: 'The long script, section by section, in his style.',
  rewrite: 'Narration check, Human Touch, style rewrites.',
  shorts: 'The session Shorts scripts.',
  seo: 'Titles, description, tags (a research loop too).',
  planning: 'Visual plan, sound plan, shot lists: JSON.',
  strategist: 'Picks tonight\'s topics; the Studio Director.',
  assistant: 'Studio Assistant and Director chat.',
};

type Routes = Record<string, RouteEntry>;

const PRESETS: { label: string; title: string; build: (keys: string[]) => Routes }[] = [
  {
    label: 'Quality',
    title: 'Claude writes (Opus for the script, Sonnet for research, Shorts, SEO, planning); Gemma polishes and plans.',
    build: (keys) => Object.fromEntries(keys.map((k) => [k,
      ['research', 'shorts', 'seo', 'strategist', 'assistant'].includes(k) ? { provider: 'claude', model: 'sonnet', fallback: 'lm_studio' }
        : k === 'script' ? { provider: 'claude', model: 'opus', fallback: 'lm_studio' }
          : { provider: 'lm_studio', model: '', fallback: 'claude' }])) as Routes,
  },
  {
    label: 'Balanced',
    title: 'Claude Opus only for the script; everything else on Gemma, Claude as its fallback.',
    build: (keys) => Object.fromEntries(keys.map((k) => [k,
      k === 'script' ? { provider: 'claude', model: 'opus', fallback: 'lm_studio' }
        : { provider: 'lm_studio', model: '', fallback: 'claude' }])) as Routes,
  },
  {
    label: 'Gemma writes',
    title: 'Gemma writes the script and the Shorts (Claude if it fails); Claude Sonnet researches, plans topics and does SEO.',
    build: (keys) => Object.fromEntries(keys.map((k) => [k,
      ['script', 'shorts', 'rewrite', 'planning'].includes(k) ? { provider: 'lm_studio', model: '', fallback: 'claude' }
        : { provider: 'claude', model: 'sonnet', fallback: 'lm_studio' }])) as Routes,
  },
  {
    label: 'All local',
    title: 'Everything on Gemma; Claude is only asked when Gemma fails.',
    build: (keys) => Object.fromEntries(keys.map((k) => [k, { provider: 'lm_studio', model: '', fallback: 'claude' }])) as Routes,
  },
];

function tokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${Math.round(n / 1000)}k`;
  return String(n);
}

export default function ModelRoutingWindow({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { toast } = useStudio();
  const [data, setData] = useState<RoutesResponse | null>(null);
  const [all, setAll] = useState<Record<Profile, Routes>>({ day: {}, night: {} });
  const [tab, setTab] = useState<Profile>('night');
  const [hours, setHours] = useState({ start: '22:00', end: '09:00' });
  const [forecast, setForecast] = useState<ForecastTokens | null>(null);
  const [busy, setBusy] = useState(false);

  // The tab being edited; `setRoutes` changes only that profile.
  const routes = all[tab];
  const setRoutes = (fn: Routes | ((prev: Routes) => Routes)) =>
    setAll((prev) => ({ ...prev, [tab]: typeof fn === 'function' ? fn(prev[tab]) : fn }));

  const load = (r: RoutesResponse) => {
    setData(r);
    setHours(r.night_hours);
    setAll({
      day: Object.fromEntries(r.jobs.map((j) => [j.key, { ...j.day }])),
      night: Object.fromEntries(r.jobs.map((j) => [j.key, { ...j.night }])),
    });
  };

  useEffect(() => {
    if (!open) return;
    getJson<RoutesResponse>('/api/llm/routes').then(load).catch((e) => toast(`Could not load the routes: ${describeError(e)}`, 'error'));
    getJson<ForecastTokens>('/api/forecast/nightly').then(setForecast).catch(() => setForecast(null));
  }, [open, toast]);

  if (!open) return null;

  const set = (key: string, patch: Partial<RouteEntry>) =>
    setRoutes((prev) => {
      const next = { ...prev[key], ...patch };
      if (patch.provider !== undefined) next.model = patch.provider === 'claude' ? (key === 'script' ? 'opus' : 'sonnet') : '';
      if (next.fallback === next.provider) next.fallback = '';
      return { ...prev, [key]: next };
    });

  const save = async () => {
    setBusy(true);
    try {
      load(await putJson<RoutesResponse>('/api/llm/routes', { routes: all.day, routes_night: all.night, night_hours: hours }));
      setForecast(await getJson<ForecastTokens>('/api/forecast/nightly'));
      toast('Model routing saved. New calls follow it at once.', 'success');
    } catch (e) {
      toast(`Could not save: ${describeError(e)}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  const muted = { color: 'var(--text-secondary)', fontSize: '0.78rem' } as const;
  const modelChoice = (key: string) => {
    const r = routes[key];
    if (!r || !data) return null;
    if (r.provider === 'claude') {
      return (
        <select className="form-control" aria-label={`${key} Claude model`} value={r.model || 'sonnet'}
          onChange={(e) => setRoutes((p) => ({ ...p, [key]: { ...p[key], model: e.target.value } }))} style={{ width: 'auto', padding: '4px 8px' }}>
          {data.claude_models.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      );
    }
    if (r.provider === 'ollama') {
      return (
        <select className="form-control" aria-label={`${key} Ollama model`} value={r.model}
          onChange={(e) => setRoutes((p) => ({ ...p, [key]: { ...p[key], model: e.target.value } }))} style={{ width: 'auto', padding: '4px 8px' }}>
          <option value="">default</option>
          {data.ollama_models.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
      );
    }
    if (r.provider === 'lm_studio') return <span style={muted}>{data.gemma_model}</span>;
    if (r.provider === 'gemini') return <span style={muted}>{data.gemini_model}</span>;
    return <span style={muted}>persona tier</span>;
  };

  return (
    <div className="modal-overlay" onClick={() => !busy && onClose()} role="dialog" aria-modal="true" aria-label="Model routing">
      <div className="panel-card" style={{ width: 860, maxWidth: 'calc(100vw - 32px)', maxHeight: '88vh', overflowY: 'auto', margin: 0 }}
        onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <h3 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Route size={18} /> Model routing
          </h3>
          <button type="button" onClick={onClose} aria-label="Close" style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer' }}><X size={18} /></button>
        </div>
        <p style={{ ...muted, margin: '6px 0 12px 0', lineHeight: 1.5 }}>
          Which model does each kind of work. If it fails, the fallback is asked, then the rest in the usual order.
          Auto keeps the persona's own tier (Settings → Model Tiers). Claude uses your Claude subscription, shared with your own Claude Code use.
        </p>

        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginBottom: 10 }}>
          <div role="tablist" aria-label="Day or night routes" style={{ display: 'inline-flex', border: '1px solid var(--border-card)', borderRadius: 8, overflow: 'hidden' }}>
            {(['night', 'day'] as Profile[]).map((p) => (
              <button key={p} type="button" role="tab" aria-selected={tab === p} onClick={() => setTab(p)}
                style={{ padding: '6px 14px', fontSize: '0.85rem', border: 'none', cursor: 'pointer', fontWeight: 600,
                  background: tab === p ? 'var(--accent, #f43f5e)' : 'transparent', color: tab === p ? '#fff' : 'var(--text-primary)' }}>
                {p === 'night' ? 'Night' : 'Day'}{data?.profile_now === p ? ' (now)' : ''}
              </button>
            ))}
          </div>
          <label style={{ ...muted, display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            Night is
            <input type="time" className="form-control" aria-label="Night starts" value={hours.start}
              onChange={(e) => setHours((h) => ({ ...h, start: e.target.value }))} style={{ width: 'auto', padding: '3px 6px' }} />
            to
            <input type="time" className="form-control" aria-label="Night ends" value={hours.end}
              onChange={(e) => setHours((h) => ({ ...h, end: e.target.value }))} style={{ width: 'auto', padding: '3px 6px' }} />
          </label>
          <span style={muted}>The 03:00 nightly run always uses Night.</span>
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
          <span style={muted}>Presets for {tab === 'night' ? 'Night' : 'Day'}:</span>
          {PRESETS.map((p) => (
            <button key={p.label} type="button" className="btn btn-outline btn-compact" title={p.title} disabled={!data}
              onClick={() => data && setRoutes(p.build(data.jobs.map((j) => j.key)))}>{p.label}</button>
          ))}
          {data && !data.claude_ready && <span style={{ ...muted, color: '#f59e0b' }}>Claude has no API key: its routes fall through.</span>}
        </div>

        {!data ? <p style={muted}>Loading…</p> : (
          <div style={{ display: 'grid', gap: 8 }}>
            {data.jobs.map((job) => {
              const r = routes[job.key] || { provider: '', model: '', fallback: '' };
              const measured = Object.entries(job.measured || {});
              return (
                <div key={job.key} style={{ border: '1px solid var(--border-card)', borderRadius: 8, padding: '10px 12px', display: 'grid', gap: 6 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    <div style={{ minWidth: 190 }}>
                      <div style={{ fontWeight: 600, fontSize: '0.88rem' }}>{job.label}</div>
                      <div style={muted}>{HINT[job.key]}</div>
                    </div>
                    <div role="radiogroup" aria-label={`${job.label} model`} style={{ display: 'inline-flex', border: '1px solid var(--border-card)', borderRadius: 8, overflow: 'hidden' }}>
                      {PROVIDERS.map((p) => (
                        <button key={p.id || 'auto'} type="button" role="radio" aria-checked={r.provider === p.id}
                          onClick={() => set(job.key, { provider: p.id })}
                          style={{
                            padding: '5px 10px', fontSize: '0.8rem', border: 'none', cursor: 'pointer',
                            background: r.provider === p.id ? 'var(--accent, #f43f5e)' : 'transparent',
                            color: r.provider === p.id ? '#fff' : 'var(--text-primary)',
                          }}>{p.label}</button>
                      ))}
                    </div>
                    {modelChoice(job.key)}
                    <label style={{ ...muted, display: 'inline-flex', alignItems: 'center', gap: 6, marginLeft: 'auto' }}>
                      then
                      <select className="form-control" aria-label={`${job.label} fallback`} value={r.fallback} disabled={!r.provider}
                        onChange={(e) => setRoutes((prev) => ({ ...prev, [job.key]: { ...prev[job.key], fallback: e.target.value as Provider } }))}
                        style={{ width: 'auto', padding: '4px 8px' }}>
                        <option value="">usual order</option>
                        {PROVIDERS.filter((p) => p.id && p.id !== r.provider).map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
                      </select>
                    </label>
                  </div>
                  {measured.length > 0 && (
                    <div style={muted}>
                      Last 7 days: {measured.map(([prov, m]) =>
                        `${PROVIDER_NAME[prov] || prov} ${m.calls} calls, ${tokens(m.in)} in / ${tokens(m.out)} out per call, ${Math.round(m.s)} s`).join(' · ')}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 14, flexWrap: 'wrap' }}>
          {forecast && (
            <span style={muted}>
              Tonight's long-form run: Claude ≈ {tokens(forecast.claude.in)} in / {tokens(forecast.claude.out)} out. {forecast.verdict}
            </span>
          )}
          <button type="button" className="btn" style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6 }} disabled={busy || !data} onClick={save}>
            <Save size={14} /> {busy ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  );
}
