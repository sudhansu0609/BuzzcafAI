import { useEffect, useState } from 'react';
import { BarChart3, Bookmark, ExternalLink, FolderPlus, RefreshCw, Sparkles } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';
import { CHANNEL_META, metaFor, workflowFor } from '../lib/channels';
import type { VideoIntel, VideoIntelSummary } from '../lib/types';

// Analyze (roadmap v6, S1): drop a video or channel link, see why it performs,
// and get a blueprint for our own version on the selected channel. Numbers
// come from the backend; a `simulated` result means no model answered and only
// the metrics are shown, labelled as such.

const fmt = (n?: number | null): string => {
  if (n == null) return '—';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
};

const mmss = (s?: number | null): string => {
  if (s == null) return '—';
  const m = Math.floor(s / 60);
  const r = Math.round(s % 60);
  return `${m}:${String(r).padStart(2, '0')}`;
};

const asList = (v: unknown): string[] => (Array.isArray(v) ? v.map((x) => (typeof x === 'string' ? x : JSON.stringify(x))) : []);

interface Factor {
  factor?: string;
  evidence?: string;
  weight?: number;
}

const factors = (v: unknown): Factor[] => (Array.isArray(v) ? (v as Factor[]) : []);

export default function Analyze() {
  const { brands, selectedChannel, setSelectedChannel, toast, navigate, refreshProjects } = useStudio();
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<VideoIntel | null>(null);
  const [recent, setRecent] = useState<VideoIntelSummary[]>([]);

  const channels = (brands.length > 0 ? brands : CHANNEL_META.map((c) => c.id)).map((id) => ({ ...metaFor(id), id }));

  const loadRecent = async () => {
    try {
      const data = await getJson<{ items: VideoIntelSummary[] }>('/api/video-intel/recent');
      setRecent(data.items || []);
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  useEffect(() => {
    loadRecent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const run = async (force = false) => {
    const target = url.trim();
    if (!target) {
      toast('Paste a YouTube video or channel link first.', 'info');
      return;
    }
    setBusy(true);
    try {
      const data = await postJson<VideoIntel>('/api/video-intel/analyze', { url: target, channel: selectedChannel, force });
      setResult(data);
      if (data.simulated) toast('No model answered: showing the numbers only.', 'info');
      await loadRecent();
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setBusy(false);
    }
  };

  const open = async (id: string) => {
    try {
      const data = await getJson<VideoIntel>(`/api/video-intel/${encodeURIComponent(id)}`);
      setResult(data);
      setUrl(data.video?.url || '');
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const blueprint = (result?.analysis?.blueprint || {}) as Record<string, unknown>;
  const titles = asList(blueprint.working_titles);
  const firstTitle = titles[0] || (result?.video?.title ? `Our take on: ${result.video.title}` : '');

  const saveTopic = async () => {
    if (!result) return;
    try {
      await postJson('/api/topics/save', {
        topic: firstTitle,
        category: 'Modelled',
        channel: selectedChannel,
        viral_potential: Math.min(10, Math.round((result.metrics?.outlier_multiple || 1) * 2)),
        country: '',
        source_type: 'video_intel',
        sources_used: [result.video?.url || ''],
        visual_requirements: [String(blueprint.thumbnail_direction || '')].filter(Boolean),
        exclusion_audit: asList(result.analysis?.do_not_copy).join('; '),
        notes: `Modelled on "${result.video?.title || result.video?.channel}". Hook: ${String(blueprint.hook_script || '').slice(0, 400)}`,
      });
      toast('Saved to the Topic Vault.', 'success');
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const startProject = async () => {
    if (!result) return;
    try {
      await postJson('/api/projects', { name: firstTitle, brand: selectedChannel, workflow_name: workflowFor(selectedChannel) });
      await refreshProjects();
      toast('Project created from the blueprint.', 'success');
      navigate('projects');
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const video = result?.video || {};
  const metrics = result?.metrics || {};
  const analysis = result?.analysis || {};
  const heat: Array<{ t: number; v: number }> = Array.isArray(video.heatmap) ? video.heatmap : [];

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div className="panel-card">
        <div className="panel-title">
          <BarChart3 size={16} /> Analyze a video or channel
        </div>
        <p style={{ opacity: 0.75, marginTop: 4 }}>
          Paste a YouTube link. You get why it performs (hook, packaging, most-replayed moments, how far above its
          channel's median it sits) and a blueprint for our version on the selected channel.
        </p>
        <div className="form-row" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            className="form-control"
            style={{ flex: '1 1 320px' }}
            placeholder="https://www.youtube.com/watch?v=… or https://www.youtube.com/@channel"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && run()}
          />
          <select className="form-control" style={{ flex: '0 1 220px' }} value={selectedChannel} onChange={(e) => setSelectedChannel(e.target.value)}>
            {channels.map((c) => (
              <option key={c.id} value={c.id}>
                {c.icon} model for {c.id}
              </option>
            ))}
          </select>
          <button className="btn" disabled={busy} onClick={() => run()}>
            {busy ? <RefreshCw size={14} className="spin" /> : <Sparkles size={14} />} {busy ? 'Analyzing… (captions + model, up to a minute)' : 'Analyze'}
          </button>
          {result && (
            <button className="btn btn-outline" disabled={busy} onClick={() => run(true)} title="Ignore the cached result">
              Re-run
            </button>
          )}
        </div>
      </div>

      {result && result.kind === 'video' && (
        <>
          <div className="panel-card" style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            {video.thumbnail && <img src={video.thumbnail} alt="" style={{ width: 240, borderRadius: 8, objectFit: 'cover' }} />}
            <div style={{ flex: 1, minWidth: 260 }}>
              <h2 style={{ margin: '0 0 4px' }}>{video.title}</h2>
              <div style={{ opacity: 0.8 }}>
                {video.channel} · uploaded {video.upload_date} · {mmss(video.duration)}{' '}
                <a href={video.url} target="_blank" rel="noreferrer" style={{ marginLeft: 8 }}>
                  <ExternalLink size={12} /> open
                </a>
              </div>
              <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                {result.simulated && <span className="status-badge status-planned">numbers only, no model</span>}
                {metrics.outlier_multiple != null && (
                  <span className="status-badge status-completed">{metrics.outlier_multiple}× the channel's median</span>
                )}
                {metrics.rank_in_recent != null && <span className="status-badge">#{metrics.rank_in_recent} of {metrics.videos_sampled + 1} recent</span>}
                {metrics.transcript_language && (
                  <span className="status-badge">captions {metrics.transcript_language}{metrics.transcript_auto ? ' (auto)' : ''}</span>
                )}
              </div>
              <div className="metrics-grid" style={{ marginTop: 12 }}>
                <Metric label="Views" value={fmt(video.view_count)} />
                <Metric label="Views / day" value={fmt(metrics.views_per_day)} />
                <Metric label="Like rate" value={metrics.like_rate_pct != null ? `${metrics.like_rate_pct}%` : '—'} />
                <Metric label="Comments / 1k" value={metrics.comments_per_1k_views ?? '—'} />
                <Metric label="Views ÷ subs" value={metrics.views_to_subs ?? '—'} />
                <Metric label="Channel median" value={fmt(metrics.recent_median_views)} />
              </div>
            </div>
          </div>

          {heat.length > 0 && (
            <div className="panel-card">
              <div className="panel-title">Most replayed</div>
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: 1, height: 60 }}>
                {heat.map((h, i) => (
                  <div
                    key={i}
                    title={`${mmss(h.t)} · ${Math.round(h.v * 100)}%`}
                    style={{ flex: 1, height: `${Math.max(4, h.v * 100)}%`, background: 'linear-gradient(#a78bfa, #6d28d9)', borderRadius: 2, opacity: 0.4 + h.v * 0.6 }}
                  />
                ))}
              </div>
              <ul style={{ marginTop: 10 }}>
                {(metrics.peaks || []).map((p: { t: number; value: number; transcript: string }, i: number) => (
                  <li key={i}>
                    <strong>{mmss(p.t)}</strong> ({Math.round(p.value * 100)}%): <em>{p.transcript || 'no captions here'}</em>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
            <div className="panel-card">
              <div className="panel-title">Why it works</div>
              <ol>
                {factors(analysis.why_it_works).map((f, i) => (
                  <li key={i} style={{ marginBottom: 6 }}>
                    <strong>{f.factor}</strong>
                    {f.weight ? <span style={{ opacity: 0.6 }}> · {f.weight}/5</span> : null}
                    <div style={{ opacity: 0.85 }}>{f.evidence}</div>
                  </li>
                ))}
              </ol>
            </div>
            <div className="panel-card">
              <div className="panel-title">The hook</div>
              <p>
                <strong>Opens with:</strong> <em>{analysis.hook?.first_line || metrics.hook_transcript?.slice(0, 200) || '—'}</em>
              </p>
              <p>
                <strong>Technique:</strong> {analysis.hook?.technique || '—'}
              </p>
              <p>
                <strong>Promise:</strong> {analysis.hook?.what_it_promises || analysis.packaging?.promise || '—'}
              </p>
              <div className="panel-title" style={{ marginTop: 12 }}>Packaging</div>
              <p>
                <strong>Title pattern:</strong> {analysis.packaging?.title_pattern || '—'}
              </p>
              <p>
                <strong>Thumbnail:</strong> {analysis.packaging?.thumbnail_read || '—'}
              </p>
              <p>
                <strong>Audience:</strong> {analysis.audience?.who || '—'} · clicks because {analysis.audience?.why_they_click || '—'} · stays because{' '}
                {analysis.audience?.why_they_stay || '—'}
              </p>
            </div>
          </div>

          {Array.isArray(analysis.structure) && analysis.structure.length > 0 && (
            <div className="panel-card">
              <div className="panel-title">Structure</div>
              <div className="timeline-container">
                {analysis.structure.map((b: { t: number; beat: string }, i: number) => (
                  <div key={i} className="timeline-step">
                    <span className="step-num">{mmss(b.t)}</span> {b.beat}
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="panel-card" style={{ borderColor: '#a78bfa' }}>
            <div className="panel-title">
              <Sparkles size={14} /> Blueprint for {selectedChannel}
            </div>
            {result.simulated && <p style={{ opacity: 0.8 }}>{analysis.note}</p>}
            {titles.length > 0 && (
              <>
                <strong>Working titles</strong>
                <ul>
                  {titles.map((t, i) => (
                    <li key={i}>{t}</li>
                  ))}
                </ul>
              </>
            )}
            {blueprint.hook_script ? (
              <>
                <strong>Hook script (first 30 s)</strong>
                <p className="parchment-editor" style={{ whiteSpace: 'pre-wrap' }}>{String(blueprint.hook_script)}</p>
              </>
            ) : null}
            {Array.isArray(blueprint.outline) && (blueprint.outline as unknown[]).length > 0 && (
              <>
                <strong>Outline</strong>
                <ol>
                  {(blueprint.outline as Array<{ segment: string; minutes: number; purpose: string }>).map((o, i) => (
                    <li key={i}>
                      <strong>{o.segment}</strong> ({o.minutes} min): {o.purpose}
                    </li>
                  ))}
                </ol>
              </>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 8 }}>
              <Fact label="Thumbnail" value={blueprint.thumbnail_direction} />
              <Fact label="Length" value={blueprint.target_length_minutes ? `${blueprint.target_length_minutes} min` : ''} />
              <Fact label="CTA" value={blueprint.cta} />
              <Fact label="Our difference" value={blueprint.differentiator} />
              <Fact label="Tags" value={asList(blueprint.tags).join(', ')} />
              <Fact label="Do not copy" value={asList(analysis.do_not_copy).join('; ')} />
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
              <button className="btn" onClick={saveTopic} disabled={!firstTitle}>
                <Bookmark size={14} /> Save as topic
              </button>
              <button className="btn btn-outline" onClick={startProject} disabled={!firstTitle}>
                <FolderPlus size={14} /> Start a project
              </button>
            </div>
          </div>
        </>
      )}

      {result && result.kind === 'channel' && (
        <>
          <div className="panel-card">
            <h2 style={{ margin: '0 0 4px' }}>{video.channel}</h2>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
              {result.simulated && <span className="status-badge status-planned">numbers only, no model</span>}
              <span className="status-badge">{metrics.videos_sampled} recent videos</span>
              <span className="status-badge">median {fmt(metrics.median_views)} views</span>
              <span className="status-badge">median length {mmss(metrics.median_duration_seconds)}</span>
            </div>
            <div className="metrics-grid">
              <Metric label="Top video" value={fmt(metrics.top_views)} />
              <Metric label="Mean views" value={fmt(metrics.mean_views)} />
              <Metric label="Titles with numbers" value={`${metrics.title_patterns?.pct_with_number ?? 0}%`} />
              <Metric label="Question titles" value={`${metrics.title_patterns?.pct_questions ?? 0}%`} />
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
            <div className="panel-card">
              <div className="panel-title">Outliers (vs the channel's median)</div>
              <ol>
                {(metrics.outliers || []).map((v: { id: string; title: string; view_count: number; outlier_multiple: number | null }) => (
                  <li key={v.id} style={{ marginBottom: 4 }}>
                    <a href={`https://www.youtube.com/watch?v=${v.id}`} target="_blank" rel="noreferrer">
                      {v.title}
                    </a>{' '}
                    · {fmt(v.view_count)} {v.outlier_multiple != null && <span style={{ opacity: 0.7 }}>({v.outlier_multiple}×)</span>}
                    <button className="btn btn-outline" style={{ marginLeft: 8, padding: '2px 8px' }} onClick={() => { setUrl(`https://www.youtube.com/watch?v=${v.id}`); }}>
                      analyze this
                    </button>
                  </li>
                ))}
              </ol>
            </div>
            <div className="panel-card">
              <div className="panel-title">What works</div>
              <ol>
                {factors(analysis.what_works).map((f, i) => (
                  <li key={i} style={{ marginBottom: 6 }}>
                    <strong>{f.factor}</strong>
                    <div style={{ opacity: 0.85 }}>{f.evidence}</div>
                  </li>
                ))}
              </ol>
              <p>
                <strong>Outlier pattern:</strong> {analysis.outlier_pattern || '—'}
              </p>
              <p>
                <strong>Title formula:</strong> {analysis.packaging?.title_formula || '—'} · <strong>Length:</strong> {analysis.packaging?.length || '—'} ·{' '}
                <strong>Cadence:</strong> {analysis.packaging?.cadence || '—'}
              </p>
            </div>
          </div>
          {Array.isArray(analysis.borrow) && analysis.borrow.length > 0 && (
            <div className="panel-card" style={{ borderColor: '#a78bfa' }}>
              <div className="panel-title">
                <Sparkles size={14} /> Borrow for {selectedChannel}
              </div>
              <ul>
                {analysis.borrow.map((b: { idea: string; for_us: string; working_title: string }, i: number) => (
                  <li key={i} style={{ marginBottom: 6 }}>
                    <strong>{b.working_title || b.idea}</strong>: {b.for_us || b.idea}
                  </li>
                ))}
              </ul>
              {asList(analysis.avoid).length > 0 && <p style={{ opacity: 0.8 }}>Avoid: {asList(analysis.avoid).join('; ')}</p>}
            </div>
          )}
        </>
      )}

      {recent.length > 0 && (
        <div className="panel-card">
          <div className="panel-title">Recent analyses</div>
          <div className="project-list">
            {recent.map((item) => (
              <div key={item.id} className="project-item" style={{ cursor: 'pointer', display: 'flex', gap: 10, alignItems: 'center' }} onClick={() => open(item.id)}>
                {item.thumbnail ? <img src={item.thumbnail} alt="" style={{ width: 64, height: 36, objectFit: 'cover', borderRadius: 4 }} /> : <BarChart3 size={18} />}
                <div style={{ flex: 1 }}>
                  <div className="project-name">{item.title}</div>
                  <div className="project-meta">
                    {item.kind} · {item.channel} · {fmt(item.view_count)} views
                    {item.outlier_multiple != null ? ` · ${item.outlier_multiple}× median` : ''} · for {item.channel_for || '—'}
                    {item.simulated ? ' · numbers only' : ''}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="metric-card">
      <div className="metric-label">{label}</div>
      <div className="metric-val">{value}</div>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: unknown }) {
  const text = value == null ? '' : String(value);
  if (!text) return null;
  return (
    <div>
      <strong>{label}:</strong> {text}
    </div>
  );
}
