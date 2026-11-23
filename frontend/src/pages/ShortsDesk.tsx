import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CalendarClock, ExternalLink, Loader2, Play, Search, Smartphone, Sparkles, TrendingUp } from 'lucide-react';
import { useStudio } from '../state/studio';
import { describeError, getJson, postJson } from '../services/api';
import NightlyControls, { type NightlyPatch, type NightlyState } from '../components/NightlyControls';

/* Shorts Desk (app/services/shorts_desk.py): find -> verify -> score ->
 * build ready-to-record 1-2 minute vertical shorts for each channel. Poem
 * text always comes from the source page (never a model's memory). */

type Filter = { key: string; label: string; options?: string[]; free?: boolean };
type Formats = Record<string, Record<string, { label: string; kind: 'poem' | 'story' | 'fiction'; filters: Filter[] }>>;
type Evidence = {
  query: string; results: number; short_results: number; median_short_views: number | null;
  max_short_views: number | null; near_duplicates: number; top: { title: string; views: number | null; seconds: number | null }[];
};
type Candidate = {
  id: string; title: string; best_title?: string; poet?: string; hook?: string; angle?: string; angle_tip?: string;
  text?: string; glosses?: string[]; source_url?: string; rights?: string; poet_died?: number | null;
  public_domain_from?: number | null; excerpted?: boolean; est_seconds?: number; notes?: { title: string; snippet: string; url: string }[];
  score?: number; verdict?: string; reasons?: string[]; subscores?: Record<string, number | null>; evidence?: Evidence; kind?: string;
};
type FindResult = { channel: string; format: string; candidates: Candidate[]; dropped_unverified?: number; seconds?: number; error?: string };
type Job<T> = { job_id: string; kind: string; state: 'running' | 'done' | 'failed'; message: string; result: T | null; error: string | null };
type Nightly = NightlyState;
type Daily = {
  enabled: boolean; time: string; per_channel: number; min_score: number; last_run: string;
  last?: { ran_at?: string; built?: { channel: string; title: string; score: number; project_id: string }[]; skipped?: { channel: string; reason: string }[] };
};

const CHANNEL_COLORS: Record<string, string> = { Life3Baje: '#f59e0b', Raat3Baje: '#ef4444', Beyond3Baje: '#8b5cf6' };
const fmtViews = (n: number | null | undefined) =>
  n == null ? '—' : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}K` : String(n);

function usePoll() {
  const timer = useRef<number | null>(null);
  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current); }, []);
  return useCallback(<T,>(jobId: string, onUpdate: (j: Job<T>) => void) => {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = window.setInterval(async () => {
      try {
        const j = await getJson<Job<T>>(`/api/shorts/jobs/${jobId}`);
        onUpdate(j);
        if (j.state !== 'running' && timer.current) { window.clearInterval(timer.current); timer.current = null; }
      } catch { /* transient */ }
    }, 2000);
  }, []);
}

export default function ShortsDesk() {
  const { toast, navigate, refreshProjects, channelFilter, setChannelFilter } = useStudio();
  const [formats, setFormats] = useState<Formats | null>(null);
  const [channel, setChannel] = useState('Life3Baje');
  const [fmt, setFmt] = useState('poem');
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [count, setCount] = useState(6);
  const [findJob, setFindJob] = useState<Job<FindResult> | null>(null);
  const [result, setResult] = useState<FindResult | null>(null);
  const [building, setBuilding] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const [daily, setDaily] = useState<Daily | null>(null);
  const [nightly, setNightly] = useState<Nightly | null>(null);
  const pollFind = usePoll();
  const pollBuild = usePoll();

  useEffect(() => {
    getJson<Formats>('/api/shorts/formats').then(setFormats).catch((e) => toast(describeError(e), 'error'));
    getJson<Daily>('/api/shorts/daily').then(setDaily).catch(() => undefined);
    getJson<Nightly>('/api/shorts/nightly').then(setNightly).catch(() => undefined);
    getJson<FindResult[]>('/api/shorts/finds').then((f) => { if (f[0]) setResult(f[0]); }).catch(() => undefined);
  }, [toast]);

  const spec = formats?.[channel]?.[fmt];
  const pickChannel = (ch: string) => {
    setChannel(ch);
    const first = Object.keys(formats?.[ch] || {})[0];
    if (first) setFmt(first);
    setFilters({});
  };

  // Follow the header's channel picker when that channel has Shorts formats.
  useEffect(() => {
    if (channelFilter && formats?.[channelFilter] && channelFilter !== channel) pickChannel(channelFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelFilter, formats]);

  const runFind = async () => {
    try {
      const job = await postJson<Job<FindResult>>('/api/shorts/find', { channel, format: fmt, filters, count });
      setFindJob(job);
      pollFind<FindResult>(job.job_id, (j) => {
        setFindJob(j);
        if (j.state === 'done' && j.result) {
          setResult(j.result);
          if (!j.result.candidates.length) toast(j.result.error || 'Nothing found that could be verified.', 'info');
        }
        if (j.state === 'failed') toast(`Find failed: ${j.error}`, 'error');
      });
    } catch (e) {
      toast(describeError(e), 'error');
    }
  };

  const makeProject = async (c: Candidate) => {
    if (!result) return;
    setBuilding((b) => ({ ...b, [c.id]: 'Writing the script…' }));
    try {
      const job = await postJson<Job<{ id: string; name: string }>>('/api/shorts/build', { channel: result.channel, format: result.format, candidate: c });
      pollBuild<{ id: string; name: string }>(job.job_id, (j) => {
        if (j.state === 'done' && j.result) {
          setBuilding((b) => ({ ...b, [c.id]: `done:${j.result!.name}` }));
          toast(`Project ready to record: ${j.result.name}`, 'success');
          refreshProjects();
        } else if (j.state === 'failed') {
          setBuilding((b) => ({ ...b, [c.id]: '' }));
          toast(`Could not build: ${j.error}`, 'error');
        }
      });
    } catch (e) {
      setBuilding((b) => ({ ...b, [c.id]: '' }));
      toast(describeError(e), 'error');
    }
  };

  const saveDaily = async (patch: Partial<Daily>) => {
    try {
      const next = await postJson<Daily>('/api/shorts/daily', patch);
      setDaily((d) => ({ ...(d || next), ...next }));
    } catch (e) {
      toast(describeError(e), 'error');
    }
  };

  const saveNightly = async (patch: NightlyPatch) => {
    try {
      setNightly(await postJson<Nightly>('/api/shorts/nightly', patch));
    } catch (e) {
      toast(describeError(e), 'error');
    }
  };

  const runDailyNow = async () => {
    try {
      const job = await postJson<Job<unknown>>('/api/shorts/daily/run', {});
      toast('Daily batch started — it finds, scores and builds for all three channels.', 'info');
      pollBuild<unknown>(job.job_id, (j) => {
        if (j.state !== 'running') {
          getJson<Daily>('/api/shorts/daily').then(setDaily).catch(() => undefined);
          refreshProjects();
          toast(j.state === 'done' ? 'Daily batch finished.' : `Daily batch failed: ${j.error}`, j.state === 'done' ? 'success' : 'error');
        }
      });
    } catch (e) {
      toast(describeError(e), 'error');
    }
  };

  const finding = findJob?.state === 'running';
  const shown = useMemo(() => (result && result.channel === channel ? result : null), [result, channel]);

  return (
    <div>
      <div className="panel-card" style={{ marginBottom: 20 }}>
        <h3 className="panel-title"><Smartphone size={22} /> Shorts scheduler</h3>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.88rem', marginTop: 0 }}>
          1-2 minute vertical shorts you record on your phone. The desk finds material, checks it against the source and
          against what's performing on YouTube Shorts, scores it, and builds a project with the script, caption and
          hashtags. Record, drop the video into the project, and Produce Video edits it.
        </p>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
          {Object.keys(formats || {}).map((ch) => (
            <button key={ch} type="button" onClick={() => { pickChannel(ch); setChannelFilter(ch); }} className="btn btn-outline"
              style={{ borderColor: channel === ch ? CHANNEL_COLORS[ch] : undefined, color: channel === ch ? CHANNEL_COLORS[ch] : undefined, fontWeight: channel === ch ? 700 : 500 }}>
              {ch}
            </button>
          ))}
          <span style={{ width: 1, background: 'var(--border-subtle)', margin: '0 6px' }} />
          {Object.entries(formats?.[channel] || {}).map(([k, f]) => (
            <button key={k} type="button" onClick={() => { setFmt(k); setFilters({}); }} className={fmt === k ? 'btn' : 'btn btn-outline'}
              style={{ padding: '6px 12px', fontSize: '0.82rem' }}>
              {f.label}
            </button>
          ))}
        </div>

        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          {spec?.filters.map((f) => (
            <label key={f.key} style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.78rem', color: 'var(--text-muted)' }}>
              {f.label}
              {f.free ? (
                <input className="form-control" aria-label={f.label} value={filters[f.key] || ''} placeholder="Any"
                  onChange={(e) => setFilters((x) => ({ ...x, [f.key]: e.target.value }))} style={{ width: 190 }} />
              ) : (
                <select className="form-control" aria-label={f.label} value={filters[f.key] || f.options?.[0] || ''}
                  onChange={(e) => setFilters((x) => ({ ...x, [f.key]: e.target.value }))} style={{ width: 210 }}>
                  {f.options?.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              )}
            </label>
          ))}
          <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.78rem', color: 'var(--text-muted)' }}>
            How many
            <input type="number" className="form-control" aria-label="How many" min={1} max={12} value={count}
              onChange={(e) => setCount(Math.max(1, Math.min(12, Number(e.target.value) || 1)))} style={{ width: 80 }} />
          </label>
          <button type="button" className="btn" onClick={runFind} disabled={finding || !spec}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            {finding ? <Loader2 size={15} className="spin" /> : <Search size={15} />}
            <span>{finding ? findJob?.message || 'Working…' : 'Find & score'}</span>
          </button>
        </div>
      </div>

      {shown && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ color: 'var(--text-muted)', fontSize: '0.82rem', margin: '0 0 10px 4px' }}>
            {shown.candidates.length} verified candidate(s)
            {shown.dropped_unverified ? ` · ${shown.dropped_unverified} dropped (text or source not found)` : ''}
            {shown.seconds != null ? ` · ${shown.seconds}s` : ''} · best first
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {shown.candidates.map((c) => {
              const verdictColor = c.verdict === 'make' ? '#34d399' : c.verdict === 'skip' ? '#f87171' : '#fbbf24';
              const b = building[c.id] || '';
              return (
                <div key={c.id} className="panel-card" style={{ margin: 0, padding: 16, borderLeft: `4px solid ${verdictColor}` }}>
                  <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                    <div style={{ textAlign: 'center', minWidth: 64 }}>
                      <div style={{ fontSize: '1.8rem', fontWeight: 800, color: verdictColor, lineHeight: 1 }}>{c.score ?? '—'}</div>
                      <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', color: verdictColor, fontWeight: 700 }}>{c.verdict}</div>
                    </div>
                    <div style={{ flex: 1, minWidth: 260 }}>
                      <div style={{ fontWeight: 700, fontSize: '1.02rem' }}>{c.best_title || c.title}</div>
                      <div style={{ color: 'var(--text-secondary)', fontSize: '0.84rem', marginTop: 2 }}>
                        {c.title}{c.poet ? ` — ${c.poet}` : ''}
                        {c.est_seconds ? ` · ~${c.est_seconds}s` : ''}
                        {c.excerpted ? ' · excerpt' : ''}
                      </div>
                      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', margin: '8px 0' }}>
                        {c.rights && (
                          <span title={c.poet_died ? `Poet died ${c.poet_died}; public domain in India from ${c.public_domain_from}` : ''}
                            style={{ fontSize: '0.72rem', padding: '2px 8px', borderRadius: 999, border: '1px solid var(--border-card)',
                              color: c.rights === 'public_domain' ? '#34d399' : c.rights === 'protected' ? '#fbbf24' : 'var(--text-muted)' }}>
                            {c.rights === 'public_domain' ? 'Public domain' : c.rights === 'protected' ? `In copyright${c.public_domain_from ? ` until ${c.public_domain_from - 1}` : ''}` : c.rights}
                          </span>
                        )}
                        {c.evidence && (
                          <span style={{ fontSize: '0.72rem', padding: '2px 8px', borderRadius: 999, border: '1px solid var(--border-card)', color: 'var(--text-secondary)', display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                            <TrendingUp size={11} /> similar shorts: median {fmtViews(c.evidence.median_short_views)}, top {fmtViews(c.evidence.max_short_views)} · {c.evidence.near_duplicates} near-duplicates
                          </span>
                        )}
                        {c.subscores && Object.entries(c.subscores).filter(([, v]) => v != null).map(([k, v]) => (
                          <span key={k} style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{k} {v}</span>
                        ))}
                      </div>
                      {c.reasons && c.reasons.length > 0 && (
                        <ul style={{ margin: '4px 0 6px 18px', padding: 0, fontSize: '0.84rem', color: 'var(--text-secondary)' }}>
                          {c.reasons.slice(0, 4).map((r, i) => <li key={i}>{r}</li>)}
                        </ul>
                      )}
                      {c.angle_tip && <div style={{ fontSize: '0.82rem', color: '#93c5fd' }}>Tip: {c.angle_tip}</div>}
                      <button type="button" className="btn btn-outline" onClick={() => setOpen((o) => ({ ...o, [c.id]: !o[c.id] }))}
                        style={{ padding: '3px 10px', fontSize: '0.76rem', marginTop: 8 }}>
                        {open[c.id] ? 'Hide' : c.text ? 'Read the text' : 'Research notes'}
                      </button>
                      {open[c.id] && (
                        <div style={{ marginTop: 10 }}>
                          {c.text && <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', fontSize: '1rem', lineHeight: 1.7, margin: 0 }}>{c.text}</pre>}
                          {c.glosses && c.glosses.length > 0 && (
                            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: 8 }}>Word meanings: {c.glosses.join(' · ')}</div>
                          )}
                          {c.notes?.map((n, i) => (
                            <div key={i} style={{ fontSize: '0.8rem', marginBottom: 6 }}>
                              <a href={n.url} target="_blank" rel="noreferrer" style={{ color: '#93c5fd' }}>{n.title}</a>
                              <div style={{ color: 'var(--text-muted)' }}>{n.snippet}</div>
                            </div>
                          ))}
                          {c.evidence?.top?.length ? (
                            <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginTop: 8 }}>
                              Top similar: {c.evidence.top.map((t) => `${t.title} (${fmtViews(t.views)})`).join(' · ')}
                            </div>
                          ) : null}
                        </div>
                      )}
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'stretch', minWidth: 150 }}>
                      {b.startsWith('done:') ? (
                        <button type="button" className="btn btn-outline" onClick={() => navigate('projects')}>
                          <Play size={14} /> <span>Open in Projects</span>
                        </button>
                      ) : (
                        <button type="button" className="btn" disabled={!!b} onClick={() => makeProject(c)}
                          style={{ display: 'inline-flex', alignItems: 'center', gap: 6, justifyContent: 'center' }}>
                          {b ? <Loader2 size={14} className="spin" /> : <Sparkles size={14} />}
                          <span>{b || 'Make project'}</span>
                        </button>
                      )}
                      {c.source_url && (
                        <a href={c.source_url} target="_blank" rel="noreferrer" style={{ fontSize: '0.76rem', display: 'inline-flex', gap: 4, alignItems: 'center', color: '#93c5fd' }}>
                          <ExternalLink size={12} /> Source
                        </a>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="panel-card">
        <h3 className="panel-title"><CalendarClock size={20} /> Daily batch (your shorts assistant)</h3>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.86rem', marginTop: 0 }}>
          Every morning it runs a find for each channel (rotating the formats), and turns the best ones into projects ready
          to record — they appear in Projects with the script in the teleprompter.
        </p>
        {daily && (
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
            <label style={{ display: 'flex', gap: 8, alignItems: 'center', cursor: 'pointer' }}>
              <input type="checkbox" aria-label="Daily batch enabled" checked={daily.enabled} onChange={(e) => saveDaily({ enabled: e.target.checked })} style={{ width: 18, height: 18 }} />
              <strong>{daily.enabled ? 'On' : 'Off'}</strong>
            </label>
            <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              at <input type="time" className="form-control" aria-label="Daily batch time" value={daily.time} onChange={(e) => saveDaily({ time: e.target.value })} style={{ width: 120 }} />
            </label>
            <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input type="number" className="form-control" aria-label="Per channel" min={1} max={5} value={daily.per_channel}
                onChange={(e) => saveDaily({ per_channel: Math.max(1, Math.min(5, Number(e.target.value) || 1)) })} style={{ width: 70 }} /> per channel
            </label>
            <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              min score <input type="number" className="form-control" aria-label="Min score" min={0} max={100} value={daily.min_score}
                onChange={(e) => saveDaily({ min_score: Math.max(0, Math.min(100, Number(e.target.value) || 0)) })} style={{ width: 80 }} />
            </label>
            <button type="button" className="btn btn-outline" onClick={runDailyNow}>Run now</button>
          </div>
        )}
        {nightly && (
          <NightlyControls
            title="Shorts run — wake the PC, run the batch, hibernate"
            blurb="Windows wakes the computer (even from hibernate) at the time below, runs the Shorts batch for all channels, offloads every model, then hibernates again — only if no render, ComfyUI job or production item is running, the GPU is idle, and nobody has used the PC for the idle minutes set here. The long-form scheduler has its own time and settings on the Long form tab."
            state={nightly}
            onSave={saveNightly}
          />
        )}
        {daily?.last?.ran_at && (
          <div style={{ marginTop: 12, fontSize: '0.84rem', color: 'var(--text-secondary)' }}>
            Last run {daily.last.ran_at}: {daily.last.built?.length || 0} project(s) built
            {daily.last.built?.map((x) => <div key={x.project_id}>• {x.channel}: {x.title} (score {x.score})</div>)}
            {daily.last.skipped?.map((x, i) => <div key={i} style={{ color: 'var(--text-muted)' }}>• {x.channel}: {x.reason}</div>)}
          </div>
        )}
      </div>
    </div>
  );
}
