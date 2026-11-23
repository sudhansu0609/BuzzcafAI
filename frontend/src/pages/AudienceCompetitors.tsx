import { useCallback, useEffect, useRef, useState } from 'react';
import { BookmarkPlus, Check, Lightbulb, Loader2, Plus, RefreshCw, Search, Sparkles, X } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';
import { CHANNEL_META } from '../lib/channels';
import type { AudienceSources } from '../lib/types';

// The Competitor Desk: the competitors' videos that beat their own channel's
// normal in a time range, why they worked, and our own version one click from
// the Topic Vault. The Studio finds the competitor channels itself (niche
// searches + who gets the views); he can remove one for good or add his own.

type Job<T> = { job_id: string; state: 'running' | 'done' | 'failed'; message: string; result: T | null; error: string | null };
type CompVideo = { id: string; title: string; channel: string; views: number; duration: number; published: string; age_days: number; views_per_day: number; outlier: number };
type CompVideos = { fetched_at: string; videos: CompVideo[] };
type Idea = { title: string; angle?: string; why_it_could_work?: string; format?: string; inspired_by?: string[] };
type Analysis = {
  sources?: { id: string; title: string; channel: string; views: number; outlier: number }[];
  videos: Record<string, string>[];
  patterns: string[];
  title_formulas: string[];
  gaps: string[];
  ideas: Idea[];
};

const RANGES = [7, 30, 90, 180, 365];
const fmtNum = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}K` : String(n));
const fmtDur = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;

export default function AudienceCompetitors() {
  const { brands, selectedChannel, setSelectedChannel, toast } = useStudio();
  const channelOptions = brands.length > 0 ? brands : CHANNEL_META.map((c) => c.id);
  const [days, setDays] = useState(30);
  const [minOutlier, setMinOutlier] = useState(0);
  const [data, setData] = useState<CompVideos | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState('');
  const [competitors, setCompetitors] = useState<AudienceSources['competitors']>([]);
  const [newChannel, setNewChannel] = useState('');
  const [savedIdeas, setSavedIdeas] = useState<Set<string>>(new Set());
  const timer = useRef<number | null>(null);
  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current); }, []);

  const [auto, setAuto] = useState<{ enabled: boolean; rediscover_days: number; last_run: string } | null>(null);
  useEffect(() => { getJson<typeof auto>('/api/competitors/settings').then(setAuto).catch(() => undefined); }, []);
  const saveAuto = async (patch: { enabled?: boolean; rediscover_days?: number }) => {
    try {
      setAuto(await postJson<NonNullable<typeof auto>>('/api/competitors/settings', patch));
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const base = `/api/competitors/${encodeURIComponent(selectedChannel)}`;

  const loadVideos = useCallback(async () => {
    try {
      setData(await getJson<CompVideos>(`${base}/videos?days=${days}&min_outlier=${minOutlier}&sort=outlier`));
    } catch (err) {
      toast(describeError(err), 'error');
    }
  }, [base, days, minOutlier, toast]);

  useEffect(() => { loadVideos(); }, [loadVideos]);
  useEffect(() => {
    getJson<Analysis>(`${base}/analyses/latest`).then(setAnalysis).catch(() => setAnalysis(null));
    getJson<AudienceSources>(`/api/audience/sources?channel=${encodeURIComponent(selectedChannel)}`)
      .then((s) => setCompetitors(s.competitors))
      .catch(() => undefined);
    setPicked(new Set());
  }, [base, selectedChannel]);

  const addChannel = async () => {
    const value = newChannel.trim();
    if (!value) return;
    try {
      const s = await postJson<AudienceSources>('/api/audience/sources', { channel: selectedChannel, competitors: [...competitors, { url: value, source: 'manual' }] });
      setCompetitors(s.competitors);
      setNewChannel('');
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const removeChannel = async (channel: string) => {
    try {
      const s = await postJson<AudienceSources>(`${base}/exclude`, { channel });
      setCompetitors(s.competitors);
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  // Runs a job and polls it; resolves with the result (null when it failed).
  const runJob = (label: string, path: string, body: unknown) => new Promise<unknown>((resolve) => {
    postJson<Job<unknown>>(path, body ?? {}).then((j) => {
      setBusy(label);
      if (timer.current) window.clearInterval(timer.current);
      timer.current = window.setInterval(async () => {
        try {
          const next = await getJson<Job<unknown>>(`/api/competitors/jobs/${j.job_id}`);
          setBusy(`${label} · ${next.message}`);
          if (next.state !== 'running') {
            if (timer.current) window.clearInterval(timer.current);
            setBusy('');
            if (next.state === 'failed') toast(next.error || 'Failed', 'error');
            resolve(next.state === 'done' ? next.result : null);
          }
        } catch { /* transient */ }
      }, 2000);
    }).catch((err) => { toast(describeError(err), 'error'); setBusy(''); resolve(null); });
  });

  const discover = async () => {
    if (busy) return;
    const found = await runJob('Finding', `${base}/discover`, {});
    if (found) {
      const s = await getJson<AudienceSources>(`/api/audience/sources?channel=${encodeURIComponent(selectedChannel)}`);
      setCompetitors(s.competitors);
      toast('Competitors found.', 'success');
    }
  };

  const scan = async () => {
    if (busy) return;
    if (await runJob('Scanning', `${base}/scan`, {})) { await loadVideos(); toast('Competitors scanned.', 'success'); }
  };

  const analyze = async (ids: string[]): Promise<Analysis | null> => {
    if (busy || ids.length === 0) return null;
    const result = await runJob('Analysing', `${base}/analyze`, { video_ids: ids.slice(0, 8) });
    if (result) setAnalysis(result as Analysis);
    return result as Analysis | null;
  };

  const evidenceFor = (idea: Idea, a: Analysis) => {
    const ids = new Set(idea.inspired_by || []);
    const src = (a.sources || []).filter((s) => ids.has(s.id));
    return src.length ? src : (a.sources || []).slice(0, 3);
  };

  const saveIdea = async (idea: Idea, a: Analysis) => {
    try {
      await postJson(`${base}/idea`, { idea, evidence: evidenceFor(idea, a) });
      setSavedIdeas((prev) => new Set(prev).add(idea.title));
      toast('Saved to the Topic Vault.', 'success');
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const makeOurVersion = async (id: string) => {
    const a = await analyze([id]);
    if (a && a.ideas?.length) await saveIdea(a.ideas[0], a);
    else if (a) toast('The analyst gave no idea for this one.', 'error');
  };

  const toggle = (id: string) => setPicked((prev) => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const rows = data?.videos || [];
  const cell: React.CSSProperties = { padding: '6px 8px', fontSize: '0.8rem', verticalAlign: 'middle' };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div className="panel-card" style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-primary)' }}>Competitors</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
              Videos that beat their own channel's normal. Learn what worked, then make our own version: never their script, footage, thumbnail or title.
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <select className="form-control" style={{ width: 'auto', fontWeight: 700 }} value={selectedChannel} onChange={(e) => setSelectedChannel(e.target.value)} aria-label="Channel">
              {channelOptions.map((b) => <option key={b} value={b}>{b}</option>)}
            </select>
            <select className="form-control" style={{ width: 'auto' }} value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Time range">
              {RANGES.map((d) => <option key={d} value={d}>Last {d} days</option>)}
            </select>
            <label style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 4 }}>
              min ×
              <input className="form-control" type="number" min={0} step={0.5} style={{ width: 70 }} value={minOutlier} onChange={(e) => setMinOutlier(Number(e.target.value) || 0)} />
            </label>
            <button type="button" className="btn" onClick={scan} disabled={!!busy} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              {busy.startsWith('Scanning') ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <RefreshCw size={14} />} Scan now
            </button>
          </div>
        </div>
        <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
          {data?.fetched_at ? `Last scanned ${new Date(data.fetched_at).toLocaleString()}` : 'Not scanned yet: find competitors below and press Scan now.'}
        </div>
        {busy && (
          <div style={{ fontSize: '0.82rem', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> {busy}
          </div>
        )}
        {competitors.length === 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 8, padding: '8px 0' }}>
            <div style={{ fontSize: '0.9rem', color: 'var(--text-primary)', fontWeight: 600 }}>The Studio will find channels in your niche.</div>
            <button type="button" className="btn" onClick={discover} disabled={!!busy} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              {busy.startsWith('Finding') ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Search size={14} />} Find competitors for me
            </button>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {competitors.map((c) => (
              <div key={c.url} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                <span style={{ fontSize: '0.68rem', fontWeight: 700, padding: '1px 6px', borderRadius: 4, backgroundColor: 'var(--bg-pill)', color: c.source === 'auto' ? 'var(--accent-primary)' : 'var(--text-primary)' }}>
                  {c.source === 'auto' ? 'auto' : 'yours'}
                </span>
                <a href={c.url} target="_blank" rel="noreferrer" style={{ color: '#38bdf8', textDecoration: 'none', fontWeight: 600 }}>{c.name || c.url}</a>
                {c.reason && <span style={{ flex: 1, minWidth: 0 }}>{c.reason}</span>}
                <button type="button" className="btn btn-outline" style={{ padding: '1px 6px', marginLeft: 'auto' }} title="Remove for good" aria-label={`Remove ${c.name || c.url}`} onClick={() => removeChannel(c.channel_id || c.url)}>
                  <X size={12} />
                </button>
              </div>
            ))}
            <button type="button" className="btn btn-outline" onClick={discover} disabled={!!busy} style={{ alignSelf: 'flex-start', padding: '4px 10px', fontSize: '0.78rem' }}>
              <Search size={13} style={{ marginRight: 4 }} /> Find competitors for me
            </button>
          </div>
        )}
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <input className="form-control" style={{ maxWidth: 320 }} value={newChannel} placeholder="Add a channel: @handle, channel id or URL" onChange={(e) => setNewChannel(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') addChannel(); }} />
          <button type="button" className="btn btn-outline" style={{ padding: '4px 10px', fontSize: '0.78rem' }} onClick={addChannel} disabled={!newChannel.trim()}>
            <Plus size={13} style={{ marginRight: 4 }} /> Add
          </button>
        </div>
        {auto && (
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <input type="checkbox" checked={auto.enabled} onChange={(e) => saveAuto({ enabled: e.target.checked })} /> Auto
            </label>
            <span>: rediscovered every</span>
            <select className="form-control" style={{ width: 'auto', padding: '1px 6px' }} value={auto.rediscover_days} onChange={(e) => saveAuto({ rediscover_days: Number(e.target.value) })}>
              {[7, 14, 30].map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
            <span>days, scanned nightly · last run {auto.last_run || 'never'}</span>
          </div>
        )}
      </div>

      {rows.length === 0 ? (
        <div className="panel-card" style={{ padding: 20, color: 'var(--text-secondary)' }}>No videos in this range{data?.fetched_at ? ' (try a longer range or a lower ×)' : ''}.</div>
      ) : (
        <div className="panel-card" style={{ padding: 8, overflowX: 'auto' }}>
          <div style={{ padding: '4px 8px 8px' }}>
            <button type="button" className="btn" disabled={!!busy || picked.size === 0} onClick={() => analyze(Array.from(picked))} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              {busy.startsWith('Analysing') ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Sparkles size={14} />} Analyze selected ({picked.size}, max 8)
            </button>
          </div>
          <table style={{ width: '100%', borderCollapse: 'collapse', color: 'var(--text-primary)' }}>
            <tbody>
              {rows.map((v) => (
                <tr key={v.id} style={{ borderTop: '1px solid var(--border-card)' }}>
                  <td style={cell}><input type="checkbox" checked={picked.has(v.id)} onChange={() => toggle(v.id)} disabled={!picked.has(v.id) && picked.size >= 8} /></td>
                  <td style={cell}><img src={`https://i.ytimg.com/vi/${v.id}/mqdefault.jpg`} alt="" width={96} height={54} style={{ borderRadius: 4, display: 'block' }} /></td>
                  <td style={{ ...cell, maxWidth: 360 }}>
                    <a href={`https://www.youtube.com/watch?v=${v.id}`} target="_blank" rel="noreferrer" style={{ color: '#38bdf8', textDecoration: 'none' }}>{v.title}</a>
                  </td>
                  <td style={cell}>{v.channel}</td>
                  <td style={cell}>{fmtNum(v.views)} views</td>
                  <td style={cell}>{fmtNum(Math.round(v.views_per_day))}/day</td>
                  <td style={cell}>{v.age_days}d</td>
                  <td style={cell}>{fmtDur(v.duration)}</td>
                  <td style={cell}>
                    <span style={{ fontWeight: 700, padding: '2px 8px', borderRadius: 4, backgroundColor: 'var(--bg-pill)', color: v.outlier >= 3 ? '#34d399' : 'var(--text-secondary)', border: v.outlier >= 3 ? '1px solid #34d399' : '1px solid transparent' }} title="Views against the median of this channel's videos">
                      ×{v.outlier}
                    </span>
                  </td>
                  <td style={cell}>
                    <button type="button" className="btn btn-outline" style={{ padding: '3px 8px', fontSize: '0.74rem' }} disabled={!!busy} onClick={() => makeOurVersion(v.id)}>
                      <Lightbulb size={12} style={{ marginRight: 4 }} /> Make our version
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {analysis && (analysis.ideas?.length > 0 || analysis.videos?.length > 0) && (
        <div className="panel-card" style={{ padding: '14px 18px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--text-primary)' }}>Why they worked</div>
          {analysis.videos.map((v, i) => {
            const src = (analysis.sources || []).find((s) => s.id === v.id);
            return (
              <div key={v.id || i} style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', borderLeft: '2px solid var(--border-card)', paddingLeft: 10 }}>
                <div style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{src?.title || v.topic || v.id}</div>
                <div>{v.why_it_worked}</div>
                {(['title_formula', 'hook', 'thumbnail_idea', 'length_note', 'emotion', 'audience'] as const).map((k) => v[k] ? (
                  <div key={k}><strong>{k.replace('_', ' ')}:</strong> {v[k]}</div>
                ) : null)}
              </div>
            );
          })}
          {([['Patterns', analysis.patterns], ['Title formulas', analysis.title_formulas], ['Gaps', analysis.gaps]] as const).map(([label, list]) => list?.length > 0 && (
            <div key={label} style={{ fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
              <strong style={{ color: 'var(--text-primary)' }}>{label}</strong>
              <ul style={{ margin: '4px 0 0 18px', padding: 0 }}>{list.map((t, i) => <li key={i}>{t}</li>)}</ul>
            </div>
          ))}
          {analysis.ideas?.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <strong style={{ color: 'var(--text-primary)' }}>Our own versions</strong>
              {analysis.ideas.map((idea, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', backgroundColor: 'var(--bg-pill)', padding: '8px 12px', borderRadius: 6 }}>
                  <div style={{ flex: 1, minWidth: 240, fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
                    <div style={{ color: 'var(--text-primary)', fontWeight: 600, fontSize: '0.95rem' }}>{idea.title}</div>
                    {idea.angle && <div>{idea.angle}</div>}
                    {idea.why_it_could_work && <div>{idea.why_it_could_work}</div>}
                    {idea.format && <div style={{ color: 'var(--text-muted)' }}>{idea.format}</div>}
                  </div>
                  <button type="button" className="btn btn-outline" style={{ padding: '4px 10px', fontSize: '0.78rem', alignSelf: 'flex-start' }} disabled={savedIdeas.has(idea.title)} onClick={() => saveIdea(idea, analysis)}>
                    {savedIdeas.has(idea.title) ? <Check size={13} /> : <BookmarkPlus size={13} />}
                    <span style={{ marginLeft: 4 }}>{savedIdeas.has(idea.title) ? 'In the vault' : 'Save to Topic Vault'}</span>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
