import { useEffect, useState, type FormEvent } from 'react';
import { Activity, AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, FolderGit2, MoonStar, PlusCircle, TrendingUp } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';
import { CHANNEL_META, workflowFor } from '../lib/channels';
import Markdown from '../components/Markdown';
import { MasterPanel } from '../components/MasterControl';
import DirectorPanel from '../components/DirectorPanel';
import NightForecast from '../components/NightForecast';
import type { AgentInfo, AutoStoryRecord } from '../lib/types';

interface NightlyReport {
  date: string;
  started_at?: string;
  headline: string;
  markdown: string;
  problems: string[];
  items: { task: string; state: string }[];
}

// "Last night" (2026-10-22): the morning report in one card, problems first.
function LastNight() {
  const [report, setReport] = useState<NightlyReport | null>(null);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    getJson<NightlyReport>('/api/nightly/report').then(setReport).catch(() => setReport(null));
  }, []);
  if (!report) return null;
  const ageDays = report.started_at ? Math.floor((Date.now() - new Date(report.started_at).getTime()) / 86_400_000) : null;
  const stale = ageDays !== null && ageDays >= 2;
  return (
    <div className="panel-card" style={{ borderLeft: `3px solid ${report.problems.length ? '#f59e0b' : stale ? '#f59e0b' : '#a78bfa'}` }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
          <MoonStar size={20} /> Last night
          <span style={{ fontSize: '0.8rem', fontWeight: 500, color: 'var(--text-secondary)' }}>
            {report.date}{stale ? ` · ${ageDays} days ago, nothing since` : ''}
          </span>
        </h3>
        <button type="button" onClick={() => setOpen((v) => !v)} style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />} {open ? 'Less' : 'The whole report'}
        </button>
      </div>
      <div style={{ marginTop: 8, color: 'var(--text-primary)', fontSize: '0.95rem' }}>{report.headline}</div>
      {stale && (
        <div style={{ marginTop: 6, fontSize: '0.82rem', color: '#fcd34d', display: 'flex', alignItems: 'center', gap: 6 }}>
          <AlertTriangle size={14} /> No nightly run has been recorded since; check the Health tab's nightly task rows.
        </div>
      )}
      {report.problems.length > 0 && (
        <ul style={{ margin: '8px 0 0', paddingLeft: 18, fontSize: '0.85rem', color: '#fcd34d' }}>
          {report.problems.map((p, i) => <li key={i}>{p}</li>)}
        </ul>
      )}
      {open && (
        <div style={{ marginTop: 12, borderTop: '1px solid var(--border-subtle)', paddingTop: 10 }}>
          <Markdown text={report.markdown} />
        </div>
      )}
    </div>
  );
}

// "Needs you" (2026-10-24, Fable review #10 / enhancement 3): the Studio
// makes content by itself but asks before publishing (STUDIO_DIRECTOR_PLAN.md).
// Every Story Desk record that reaches a publishable state defaults to
// `review.state: "needs_review"`; this is where the creator approves,
// rejects (with a reason, fed to the decision log) or asks for another take.
function NeedsYou() {
  const { toast } = useStudio();
  const [records, setRecords] = useState<AutoStoryRecord[]>([]);
  const [busy, setBusy] = useState<Record<string, boolean>>({});

  const load = () => {
    getJson<{ records: AutoStoryRecord[] }>('/api/auto_story/records')
      .then((r) => setRecords(r.records || []))
      .catch(() => setRecords([]));
  };
  useEffect(() => { load(); }, []);

  const needsReview = records.filter((r) => (r.review?.state || '') === 'needs_review');

  const act = async (id: string, fn: () => Promise<unknown>, okMsg: string) => {
    if (busy[id]) return;
    setBusy((b) => ({ ...b, [id]: true }));
    try {
      await fn();
      toast(okMsg, 'success');
      load();
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setBusy((b) => ({ ...b, [id]: false }));
    }
  };

  const approve = (id: string) => act(id, () => postJson(`/api/auto_story/${encodeURIComponent(id)}/approve`, {}), 'Approved.');
  const reject = (id: string) => {
    const reason = window.prompt('Reason for rejecting this?', '');
    if (reason === null) return;
    void act(id, () => postJson(`/api/auto_story/${encodeURIComponent(id)}/reject`, { reason }), 'Rejected.');
  };
  const regenerate = (id: string) => act(id, () => postJson(`/api/auto_story/${encodeURIComponent(id)}/regenerate`, {}), 'Making another take…');

  if (needsReview.length === 0) return null;

  return (
    <div className="panel-card" style={{ borderLeft: '3px solid #f59e0b' }}>
      <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0 }}>
        <AlertTriangle size={20} /> Needs you ({needsReview.length})
      </h3>
      <p style={{ color: 'var(--text-secondary)', fontSize: '0.84rem', marginTop: 6 }}>
        Made by itself; nothing here publishes until you approve it.
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 6 }}>
        {needsReview.map((r) => (
          <div key={r.project_id} style={{ display: 'flex', gap: 12, alignItems: 'flex-start', padding: '10px 0', borderTop: '1px solid var(--border-subtle)' }}>
            {r.cover ? (
              <img src={`/api/auto_story/${encodeURIComponent(r.project_id)}/preview/cover`} alt=""
                style={{ width: 64, height: 64, objectFit: 'cover', borderRadius: 6, flexShrink: 0 }} />
            ) : r.final ? (
              <video src={`/api/auto_story/${encodeURIComponent(r.project_id)}/preview/video`} muted
                style={{ width: 64, height: 64, objectFit: 'cover', borderRadius: 6, flexShrink: 0 }} />
            ) : null}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{r.name || r.project_id}</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{r.brand} · {r.format}</div>
              {r.caption && (
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: 4, whiteSpace: 'pre-wrap' }}>
                  {r.caption}
                </div>
              )}
            </div>
            <div style={{ display: 'flex', gap: 6, flexShrink: 0, flexWrap: 'wrap' }}>
              <button type="button" className="btn btn-outline" style={{ padding: '3px 10px', fontSize: '0.76rem' }}
                disabled={!!busy[r.project_id]} onClick={() => approve(r.project_id)}>Approve</button>
              <button type="button" className="btn btn-outline" style={{ padding: '3px 10px', fontSize: '0.76rem' }}
                disabled={!!busy[r.project_id]} onClick={() => reject(r.project_id)}>Reject</button>
              <button type="button" className="btn btn-outline" style={{ padding: '3px 10px', fontSize: '0.76rem' }}
                disabled={!!busy[r.project_id]} onClick={() => regenerate(r.project_id)}>Regenerate</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const PROVIDER_LABEL: Record<string, string> = {
  gemini: 'Google Gemini',
  openai: 'OpenAI',
  lm_studio: 'Local LM Studio',
};

export default function Dashboard() {
  const { projects: allProjects, settings, health, healthInfo, brands, workflows, refreshProjects, navigate, toast, channelFilter, selectedChannel } = useStudio();
  // Counts follow the header's channel picker ('' = all channels).
  const projects = channelFilter
    ? allProjects.filter((p) => (p.brand || '').toLowerCase() === channelFilter.toLowerCase())
    : allProjects;
  const [agentCount, setAgentCount] = useState<number | null>(null);
  const [name, setName] = useState('');
  const [brand, setBrand] = useState(channelFilter || selectedChannel || 'Beyond3Baje');
  const [workflow, setWorkflow] = useState(workflowFor(channelFilter || selectedChannel || 'Beyond3Baje'));
  const [creating, setCreating] = useState(false);
  const [allowAll, setAllowAll] = useState(false);
  const [durationMin, setDurationMin] = useState(8);
  // A video he already has: the project is created and produced from it
  // straight away (record-first), with no script written.
  const [recording, setRecording] = useState('');
  const [browsing, setBrowsing] = useState(false);
  // His own script: the project skips research and writing.
  const [ownScript, setOwnScript] = useState('');

  const brandOptions = brands.length > 0 ? brands : CHANNEL_META.map((c) => c.id);
  const workflowOptions = workflows.map((w) => w.id || w.name);
  // What the chosen workflow will actually do, before anything is created
  // (roadmap v9, C2).
  const chosen = workflows.find((w) => (w.id || w.name) === workflow) || null;

  useEffect(() => {
    getJson<{ agents?: AgentInfo[]; count?: number }>('/api/agents')
      .then((d) => setAgentCount(d.count ?? (d.agents || []).length))
      .catch(() => setAgentCount(null));
  }, [health]);

  const pickBrand = (value: string) => {
    setBrand(value);
    const suggested = workflowFor(value);
    if (workflowOptions.length === 0 || workflowOptions.includes(suggested)) setWorkflow(suggested);
  };

  // A channel picked in the header becomes the new project's channel.
  useEffect(() => {
    if (channelFilter) pickBrand(channelFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channelFilter]);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim() || creating) return;
    setCreating(true);
    const video = recording.trim();
    try {
      const created = await postJson<{ id: string }>('/api/projects', { name: name.trim(), brand, workflow_name: workflow, allow_all: allowAll, target_duration_minutes: durationMin, ...(ownScript.trim() ? { own_script: ownScript.trim() } : {}) });
      if (video) {
        try {
          await postJson(`/api/projects/${encodeURIComponent(created.id)}/produce_video`, { recording_path: video });
          toast(`Project "${name.trim()}" created and sent to production.`, 'success');
        } catch (err) {
          toast(`Project created, but production did not start: ${describeError(err)}. Start it from the Projects page.`, 'error');
        }
      } else {
        toast(`Project "${name.trim()}" created.`, 'success');
      }
      setName('');
      setRecording('');
      setOwnScript('');
      await refreshProjects();
      navigate('projects');
    } catch (err) {
      toast(`Could not create the project: ${describeError(err)}`, 'error');
    } finally {
      setCreating(false);
    }
  };

  const browseRecording = async () => {
    setBrowsing(true);
    try {
      const res = await postJson<{ path: string | null }>('/api/produce/browse_recording', {});
      if (res?.path) setRecording(res.path);
    } catch (err) {
      toast(`Browse failed: ${describeError(err)}`, 'error');
    } finally {
      setBrowsing(false);
    }
  };

  const inProgress = projects.filter((p) => p.status !== 'completed' && p.status !== 'archived').length;
  const archivedCount = projects.filter((p) => p.status === 'archived').length;
  const provider = settings?.selected_provider ? PROVIDER_LABEL[settings.selected_provider] || settings.selected_provider : '—';

  return (
    <div>
      <div className="metrics-grid">
        <div className="metric-card">
          <div className="metric-icon-bg"><FolderGit2 /></div>
          <span className="metric-label">Projects</span>
          <span className="metric-val">{projects.length - archivedCount}</span>
          <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>{inProgress} in progress{archivedCount ? ` · ${archivedCount} archived` : ''}</span>
        </div>
        <div className="metric-card">
          <div className="metric-icon-bg"><Activity /></div>
          <span className="metric-label">AI provider</span>
          <span className="metric-val" style={{ fontSize: '1.25rem', marginTop: 10, color: '#f43f5e' }}>{provider}</span>
        </div>
        <div className="metric-card">
          <div className="metric-icon-bg"><CheckCircle2 /></div>
          <span className="metric-label">Registered agents</span>
          <span className="metric-val">{agentCount ?? '—'}</span>
        </div>
        <div className="metric-card">
          <div className="metric-icon-bg"><TrendingUp /></div>
          <span className="metric-label">Backend</span>
          <span className="metric-val" style={{ color: health === 'online' ? '#4ade80' : health === 'offline' ? '#f87171' : '#94a3b8', fontSize: '1.25rem', marginTop: 10 }}>
            {health === 'online' ? `online${healthInfo?.version ? ` v${healthInfo.version}` : ''}` : health === 'offline' ? 'offline' : 'checking…'}
          </span>
        </div>
      </div>

      <MasterPanel />

      <NightForecast />

      <DirectorPanel />

      <LastNight />

      <NeedsYou />

      <div className="panel-card">
        <h3 className="panel-title"><PlusCircle size={20} /> New production project</h3>
        <form onSubmit={create}>
          <div className="form-row">
            <div className="form-group">
              <label>Title</label>
              <input type="text" className="form-control" aria-label="Title" placeholder="e.g. The vanishing guard of Bhangarh Fort" value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="form-group">
              <label>Channel</label>
              <select className="form-control" aria-label="Channel" value={brand} onChange={(e) => pickBrand(e.target.value)}>
                {brandOptions.map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label>Workflow</label>
              {workflowOptions.length > 0 ? (
                <select className="form-control" aria-label="Workflow" value={workflow} onChange={(e) => setWorkflow(e.target.value)}>
                  {workflowOptions.map((w) => <option key={w} value={w}>{w}</option>)}
                </select>
              ) : (
                <input type="text" className="form-control" aria-label="Workflow" value={workflow} onChange={(e) => setWorkflow(e.target.value)} />
              )}
            </div>
            <div className="form-group">
              <label>Target length (min)</label>
              <input
                type="number"
                className="form-control"
                aria-label="Target length (min)"
                min={0.5}
                max={180}
                step={0.5}
                value={durationMin}
                onChange={(e) => setDurationMin(Number(e.target.value))}
              />
            </div>
          </div>
          {chosen?.steps?.length ? (
            <div style={{ margin: '4px 0 20px 0' }}>
              <div style={{ fontSize: '0.8rem', color: '#94a3b8', marginBottom: 10 }}>
                {chosen.steps.length} steps{chosen.description ? ` · ${chosen.description}` : ''}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {chosen.steps.map((s, i) => (
                  <div
                    key={s.name}
                    title={s.description}
                    style={{ backgroundColor: 'var(--bg-subcard)', border: '1px solid var(--border-card)', borderRadius: 8, padding: '8px 12px', fontSize: '0.78rem', maxWidth: 240 }}
                  >
                    <div style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{i + 1}. {s.name}</div>
                    <div style={{ color: 'var(--text-secondary)' }}>
                      {s.agent_role}
                      {s.requires_approval && <span style={{ color: 'var(--accent-primary)' }}> · approval</span>}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          <div style={{ marginBottom: 18 }}>
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: '0.88rem', color: 'var(--text-primary)' }}>
              <input
                type="checkbox"
                aria-label="Allow all steps"
                checked={allowAll}
                onChange={(e) => setAllowAll(e.target.checked)}
                style={{ width: 16, height: 16, accentColor: '#10b981', cursor: 'pointer' }}
              />
              <span>Allow all steps (run continuously without waiting for manual approval)</span>
            </label>
          </div>
          <div className="form-group" style={{ marginBottom: 18 }}>
            <label>Already have the video? (optional)</label>
            <div style={{ display: 'flex', gap: 8 }}>
              <input
                type="text"
                className="form-control"
                aria-label="Existing video"
                placeholder="Path to your recording -- production starts from it, no script written"
                value={recording}
                onChange={(e) => setRecording(e.target.value)}
              />
              <button type="button" className="btn btn-outline" onClick={browseRecording} disabled={browsing || health === 'offline'}>
                {browsing ? 'Browsing…' : 'Browse'}
              </button>
            </div>
          </div>
          <div className="form-group" style={{ marginBottom: 18 }}>
            <label>My own script (optional) -- paste it and the Studio skips research and writing</label>
            <textarea
              className="form-control"
              aria-label="My own script"
              rows={5}
              placeholder="Paste your script here"
              value={ownScript}
              onChange={(e) => setOwnScript(e.target.value)}
            />
          </div>
          <button type="submit" className="btn" disabled={creating || health === 'offline'}>
            <PlusCircle size={18} />
            <span>{creating ? 'Creating…' : recording.trim() ? 'Create & start production' : 'Create project'}</span>
          </button>
          {health === 'offline' && <span style={{ marginLeft: 12, color: '#fca5a5', fontSize: '0.85rem' }}>Backend offline.</span>}
        </form>
      </div>
    </div>
  );
}
