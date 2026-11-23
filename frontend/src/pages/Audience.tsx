import { useCallback, useEffect, useRef, useState } from 'react';
import { BookmarkPlus, Check, ChevronDown, ChevronRight, Ear, Loader2, MessageSquareQuote, Play, RefreshCw, Save, Youtube } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';
import { CHANNEL_META } from '../lib/channels';
import AudienceCompetitors from './AudienceCompetitors';
import type { AudienceFinding, AudienceRun, AudienceSettings, AudienceSources } from '../lib/types';

// The Audience Desk (2026-10-22): what viewers ask for in the comments under
// the creator's own videos and under the big channels of the same niche,
// each finding with the comments that say so, one click from the vault.

type Job<T> = { job_id: string; kind: string; state: 'running' | 'done' | 'failed'; message: string; result: T | null; error: string | null };

const KIND_COLOURS: Record<string, string> = {
  story_request: '#f472b6',
  question: '#38bdf8',
  own_encounter: '#a78bfa',
  complaint: '#f59e0b',
  praise: '#34d399',
};
const VAULT_KINDS = new Set(['story_request', 'question', 'own_encounter']);

const fmtNum = (n: number | null | undefined) =>
  n == null ? '—' : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}K` : String(n);

function usePoll() {
  const timer = useRef<number | null>(null);
  useEffect(() => () => { if (timer.current) window.clearInterval(timer.current); }, []);
  return useCallback(<T,>(jobId: string, onUpdate: (j: Job<T>) => void) => {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = window.setInterval(async () => {
      try {
        const j = await getJson<Job<T>>(`/api/audience/jobs/${jobId}`);
        onUpdate(j);
        if (j.state !== 'running' && timer.current) { window.clearInterval(timer.current); timer.current = null; }
      } catch { /* transient */ }
    }, 2000);
  }, []);
}

function FindingCard({ item, onSave, saving }: { item: AudienceFinding; onSave: () => void; saving: boolean }) {
  const [open, setOpen] = useState(false);
  const colour = KIND_COLOURS[item.kind] || 'var(--text-secondary)';
  const saved = !!item.saved_topic_id;
  return (
    <div className="panel-card" style={{ padding: '12px 16px', borderLeft: `3px solid ${colour}`, opacity: item.in_niche === false ? 0.65 : 1 }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 240 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
            <span style={{ fontSize: '0.72rem', fontWeight: 700, color: colour, backgroundColor: 'var(--bg-pill)', padding: '2px 8px', borderRadius: 4 }}>
              {item.kind_label || item.kind}
            </span>
            {item.in_niche === false && (
              <span style={{ fontSize: '0.72rem', fontWeight: 600, color: 'var(--text-muted)', border: '1px solid var(--border-card)', padding: '1px 7px', borderRadius: 4 }} title="Asked under a video in the search results, but not something this channel would make">
                off-niche
              </span>
            )}
            <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
              <strong style={{ color: 'var(--text-primary)' }}>{item.mentions}</strong> viewer{item.mentions === 1 ? '' : 's'}
              {' · '}{fmtNum(item.likes)} likes on their comments
              {' · '}{item.videos.length} video{item.videos.length === 1 ? '' : 's'}
            </span>
          </div>
          <div style={{ fontSize: '1.02rem', fontWeight: 600, color: 'var(--text-primary)' }}>{item.topic}</div>
          {item.why && <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: 2 }}>{item.why}</div>}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }} title="Demand score: mentions, likes and how many videos it came up under">score {item.score}</span>
          {VAULT_KINDS.has(item.kind) && (
            <button type="button" className="btn btn-outline" style={{ padding: '4px 10px', fontSize: '0.78rem' }} disabled={saving || saved} onClick={onSave}>
              {saved ? <Check size={13} /> : saving ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> : <BookmarkPlus size={13} />}
              <span style={{ marginLeft: 4 }}>{saved ? 'In the vault' : 'Save to vault'}</span>
            </button>
          )}
        </div>
      </div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.78rem', padding: '6px 0 0 0', display: 'flex', alignItems: 'center', gap: 4 }}
      >
        {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
        <MessageSquareQuote size={12} /> {open ? 'Hide the comments' : 'Show the comments'}
      </button>
      {open && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {item.quotes.map((q, i) => (
            <div key={i} style={{ fontSize: '0.82rem', color: 'var(--text-primary)', backgroundColor: 'var(--bg-pill)', padding: '6px 10px', borderRadius: 6, borderLeft: '2px solid var(--border-card)' }}>
              “{q}”
            </div>
          ))}
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {item.videos.map((v) => (
              <a key={v.id} href={`https://www.youtube.com/watch?v=${v.id}`} target="_blank" rel="noreferrer" style={{ color: '#38bdf8', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <Youtube size={12} /> {v.channel ? `${v.channel}: ` : ''}{(v.title || v.id).slice(0, 60)}
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function CommentsTab() {
  const { brands, selectedChannel, setSelectedChannel, toast } = useStudio();
  const channelOptions = brands.length > 0 ? brands : CHANNEL_META.map((c) => c.id);
  const [sources, setSources] = useState<AudienceSources | null>(null);
  const [queriesText, setQueriesText] = useState('');
  const [competitorsText, setCompetitorsText] = useState('');
  const [sourcesDirty, setSourcesDirty] = useState(false);
  const [run, setRun] = useState<AudienceRun | null>(null);
  const [job, setJob] = useState<Job<AudienceRun> | null>(null);
  const [settings, setSettings] = useState<AudienceSettings | null>(null);
  const [saving, setSaving] = useState<string>('');
  const [showSources, setShowSources] = useState(false);
  const [showVideos, setShowVideos] = useState(false);
  const [kindFilter, setKindFilter] = useState<string>('');
  const poll = usePoll();

  const load = useCallback(async (channel: string) => {
    try {
      const src = await getJson<AudienceSources>(`/api/audience/sources?channel=${encodeURIComponent(channel)}`);
      setSources(src);
      setQueriesText(src.queries.join('\n'));
      setCompetitorsText(src.competitors.map((c) => c.url).join('\n'));
      setSourcesDirty(false);
    } catch (err) {
      toast(describeError(err), 'error');
    }
    try {
      setRun(await getJson<AudienceRun>(`/api/audience/latest?channel=${encodeURIComponent(channel)}`));
    } catch {
      setRun(null);
    }
  }, [toast]);

  useEffect(() => { load(selectedChannel); }, [selectedChannel, load]);
  useEffect(() => { getJson<AudienceSettings>('/api/audience/settings').then(setSettings).catch(() => undefined); }, []);

  const saveSources = async () => {
    try {
      const src = await postJson<AudienceSources>('/api/audience/sources', {
        channel: selectedChannel,
        queries: queriesText.split('\n').map((s) => s.trim()).filter(Boolean),
        competitors: competitorsText.split('\n').map((s) => s.trim()).filter(Boolean),
      });
      setSources(src);
      setSourcesDirty(false);
      toast('Sources saved.', 'success');
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const mine = async () => {
    if (job?.state === 'running') return;
    if (sourcesDirty) await saveSources();
    try {
      const j = await postJson<Job<AudienceRun>>('/api/audience/mine', { channel: selectedChannel });
      setJob(j);
      poll<AudienceRun>(j.job_id, (next) => {
        setJob(next);
        if (next.state === 'done' && next.result) {
          setRun(next.result);
          toast(`${next.result.findings.length} findings from ${next.result.comments_read} comments.`, 'success');
        } else if (next.state === 'failed') {
          toast(next.error || 'Mining failed', 'error');
        }
      });
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const saveFinding = async (f: AudienceFinding) => {
    setSaving(f.topic);
    try {
      await postJson('/api/audience/save', { channel: selectedChannel, finding: f });
      setRun((prev) => prev ? { ...prev, findings: prev.findings.map((x) => (x.topic === f.topic && x.kind === f.kind ? { ...x, saved_topic_id: 'saved' } : x)) } : prev);
      toast('Saved to the vault with the comments as evidence.', 'success');
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setSaving('');
    }
  };

  const patchSettings = async (patch: Partial<AudienceSettings>) => {
    try {
      setSettings(await postJson<AudienceSettings>('/api/audience/settings', patch));
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const running = job?.state === 'running';
  const findings = (run?.findings || []).filter((f) => !kindFilter || f.kind === kindFilter);
  const kinds = Array.from(new Set((run?.findings || []).map((f) => f.kind)));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div className="panel-card" style={{ padding: '16px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ width: 40, height: 40, borderRadius: '50%', backgroundColor: 'var(--bg-pill)', border: '1px solid #f472b6', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#f472b6' }}>
              <Ear size={22} />
            </div>
            <div>
              <div style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-primary)' }}>Audience Desk</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                What viewers ask for in the comments under your videos and under the big channels of the niche. Every finding carries the comments that say so.
              </div>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <select className="form-control" style={{ width: 'auto', fontWeight: 700 }} value={selectedChannel} onChange={(e) => setSelectedChannel(e.target.value)} aria-label="Channel">
              {channelOptions.map((b) => <option key={b} value={b}>{b}</option>)}
            </select>
            <button type="button" className="btn" onClick={mine} disabled={running} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              {running ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Play size={14} />}
              {running ? 'Reading comments…' : run?.ran_at ? 'Read the comments again' : 'Read the comments'}
            </button>
          </div>
        </div>
        {running && (
          <div style={{ marginTop: 10, fontSize: '0.82rem', color: 'var(--accent-primary)', display: 'flex', alignItems: 'center', gap: 8 }}>
            <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} /> {job?.message}
          </div>
        )}
        {job?.state === 'failed' && <div style={{ marginTop: 10, fontSize: '0.82rem', color: '#f87171' }}>{job.error}</div>}

        <button type="button" onClick={() => setShowSources((v) => !v)} style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.8rem', padding: '10px 0 0 0', display: 'flex', alignItems: 'center', gap: 4 }}>
          {showSources ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          Where it reads: {sources ? `${sources.own.length} own channel${sources.own.length === 1 ? '' : 's'}, ${sources.competitors.length} competitor${sources.competitors.length === 1 ? '' : 's'}, ${sources.queries.length} searches` : '…'}
        </button>
        {showSources && sources && (
          <div style={{ marginTop: 8, display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
            <label style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: 4 }}>
              YouTube searches, one per line (the niche's biggest videos by views are read)
              <textarea className="form-control" rows={5} value={queriesText} onChange={(e) => { setQueriesText(e.target.value); setSourcesDirty(true); }} />
            </label>
            <label style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: 4 }}>
              Competitor channels to always read: @handle, channel id or URL, one per line
              <textarea className="form-control" rows={5} value={competitorsText} placeholder="@khoonimonday" onChange={(e) => { setCompetitorsText(e.target.value); setSourcesDirty(true); }} />
            </label>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span>Your own channel{sources.own.length === 1 ? '' : 's'}: {sources.own.length ? sources.own.join(', ') : 'none connected (Bulk Editor → YouTube channels)'}</span>
              <button type="button" className="btn btn-outline" style={{ alignSelf: 'flex-start', padding: '4px 10px', fontSize: '0.78rem' }} onClick={saveSources} disabled={!sourcesDirty}>
                <Save size={13} style={{ marginRight: 4 }} /> Save sources
              </button>
              {settings && (
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', marginTop: 6 }}>
                  <input type="checkbox" checked={settings.enabled} onChange={(e) => patchSettings({ enabled: e.target.checked })} />
                  Read the comments every night and put the top {settings.auto_save_top} requests per channel in the vault
                </label>
              )}
              {settings?.last?.ran_at && (
                <span style={{ color: 'var(--text-muted)' }}>
                  Last night: {new Date(settings.last.ran_at).toLocaleString()} · {settings.last.saved?.length || 0} saved
                  {settings.last.failed && settings.last.failed.length > 0 ? ` · ${settings.last.failed.length} failed` : ''}
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {run?.ran_at ? (
        <>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>
            <span>
              Read {new Date(run.ran_at).toLocaleString()} · {run.comments_read} comments under {run.videos.length} videos · {run.seconds ? `${Math.round(run.seconds / 60)} min` : ''}
              <button type="button" onClick={() => setShowVideos((v) => !v)} style={{ background: 'none', border: 'none', color: '#38bdf8', cursor: 'pointer', fontSize: '0.8rem', marginLeft: 8 }}>
                {showVideos ? 'hide the videos' : 'which videos?'}
              </button>
            </span>
            <span style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              <button type="button" onClick={() => setKindFilter('')} className="btn btn-outline" style={{ padding: '2px 8px', fontSize: '0.74rem', opacity: kindFilter ? 0.6 : 1 }}>All ({run.findings.length})</button>
              {kinds.map((k) => (
                <button key={k} type="button" onClick={() => setKindFilter(kindFilter === k ? '' : k)} className="btn btn-outline" style={{ padding: '2px 8px', fontSize: '0.74rem', borderColor: KIND_COLOURS[k], color: KIND_COLOURS[k], opacity: kindFilter && kindFilter !== k ? 0.5 : 1 }}>
                  {(run.findings.find((f) => f.kind === k)?.kind_label) || k} ({run.findings.filter((f) => f.kind === k).length})
                </button>
              ))}
              <button type="button" className="btn btn-outline" style={{ padding: '2px 8px', fontSize: '0.74rem' }} onClick={() => load(selectedChannel)} title="Reload"><RefreshCw size={12} /></button>
            </span>
          </div>
          {showVideos && (
            <div className="panel-card" style={{ padding: '10px 14px', fontSize: '0.8rem', display: 'flex', flexDirection: 'column', gap: 4 }}>
              {run.videos.map((v) => (
                <div key={v.id} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', width: 70 }}>{v.source}</span>
                  <a href={`https://www.youtube.com/watch?v=${v.id}`} target="_blank" rel="noreferrer" style={{ color: '#38bdf8', textDecoration: 'none' }}>{v.channel ? `${v.channel}: ` : ''}{v.title || v.id}</a>
                  <span style={{ color: 'var(--text-secondary)' }}>{fmtNum(v.views)} views · {v.comments_read ?? 0} of {fmtNum(v.comment_count)} comments read</span>
                </div>
              ))}
            </div>
          )}
          {findings.length === 0 ? (
            <div className="panel-card" style={{ padding: 20, color: 'var(--text-secondary)' }}>Nothing asked for in these comments.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {findings.map((f) => (
                <FindingCard key={`${f.kind}-${f.topic}`} item={f} saving={saving === f.topic} onSave={() => saveFinding(f)} />
              ))}
            </div>
          )}
        </>
      ) : (
        <div className="panel-card" style={{ padding: 32, textAlign: 'center', color: 'var(--text-secondary)' }}>
          <Ear size={36} style={{ opacity: 0.4, marginBottom: 10 }} />
          <p style={{ margin: 0, color: 'var(--text-primary)' }}>No comments read for {selectedChannel} yet.</p>
          <p style={{ margin: '6px 0 0', fontSize: '0.85rem' }}>Press “Read the comments”: the niche's biggest videos are searched, their top comments pulled, and the viewers' requests listed with the proof. About a minute per ten videos.</p>
        </div>
      )}
    </div>
  );
}

export default function Audience() {
  const [tab, setTab] = useState<'comments' | 'competitors'>('comments');
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', gap: 8 }}>
        {([['comments', 'Comments'], ['competitors', 'Competitors']] as const).map(([id, label]) => (
          <button key={id} type="button" className={tab === id ? 'btn' : 'btn btn-outline'} style={{ padding: '4px 14px', fontSize: '0.85rem' }} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </div>
      {tab === 'comments' ? <CommentsTab /> : <AudienceCompetitors />}
    </div>
  );
}
