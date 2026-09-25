import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  AlertCircle,
  Check,
  CheckCheck,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Clock,
  Copy,
  Download,
  ExternalLink,
  FastForward,
  FileText,
  Filter,
  Layers,
  Maximize2,
  Mic,
  Play,
  Printer,
  RotateCw,
  Search,
  ShieldAlert,
  Trash2,
  Video,
  X,
} from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, deleteJson, describeError, ApiError } from '../services/api';
import Markdown from '../components/Markdown';
import type { Project, StepRecord, WorkflowStepInfo, ProduceVideoStatus } from '../lib/types';

// Mirrors backend/integrations/buzzedit_settings.py::_BRAND_GENRE -- client
// side purely to prefill the style-override form; the backend's copy is the
// one that actually decides the render (this just saves a round trip).
const BRAND_GENRE: Record<string, string> = {
  beyond3baje: 'documentary',
  raat3baje: 'horror',
  khayal3baje: 'horror',
  life3baje: 'general',
  originals: 'general',
};

function genreForBrand(brand: string): string {
  const key = (brand || '').toLowerCase().replace(/[^a-z0-9]/g, '');
  return BRAND_GENRE[key] || 'general';
}

function history(p: Project): StepRecord[] {
  return (p.history || p.steps_history || []) as StepRecord[];
}

function lastStep(p: Project): StepRecord | null {
  const h = history(p);
  return h.length ? h[h.length - 1] : null;
}

// Where each workflow step stands: the newest history record for that step
// wins, and anything the run has not reached yet is pending (roadmap v9, C2).
function stepState(p: Project, step: WorkflowStepInfo): 'done' | 'current' | 'failed' | 'waiting' | 'pending' {
  const records = history(p).filter((h) => h.step_name === step.name);
  const record = records.length ? records[records.length - 1] : null;
  if (record?.status === 'failed') return 'failed';
  if (record?.status === 'paused_for_approval') return 'waiting';
  if (record?.status === 'completed') return 'done';
  if (p.current_step === step.name) return 'current';
  return record ? 'current' : 'pending';
}

const STATE_COLOR: Record<string, string> = {
  done: '#34d399',
  current: '#f59e0b',
  failed: '#ef4444',
  waiting: '#a78bfa',
  pending: '#64748b',
};

function formatProjectId(id: string): string {
  if (id.length <= 26) return id;
  const parts = id.split('_');
  if (parts.length >= 3) {
    const date = parts[0];
    const brand = parts[1];
    const rest = parts.slice(2).join('_');
    const shortRest = rest.length > 14 ? `${rest.slice(0, 6)}…${rest.slice(-6)}` : rest;
    return `${date}_${brand}_${shortRest}`;
  }
  return `${id.slice(0, 12)}…${id.slice(-10)}`;
}

function CopyButton({ text, label = 'Copy project ID' }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button
      type="button"
      onClick={copy}
      title={copied ? 'Copied to clipboard!' : label}
      style={{
        background: 'none',
        border: 'none',
        padding: '2px 4px',
        color: copied ? '#34d399' : 'var(--text-muted)',
        cursor: 'pointer',
        display: 'inline-flex',
        alignItems: 'center',
        gap: 3,
        borderRadius: 4,
      }}
    >
      {copied ? <Check size={12} style={{ color: '#34d399' }} /> : <Copy size={12} />}
      <span style={{ fontSize: '0.72rem' }}>{copied ? 'Copied' : ''}</span>
    </button>
  );
}

export default function Projects() {
  const { projects, workflows, refreshProjects, toast, confirm, health } = useStudio();
  const [runningId, setRunningId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [feedback, setFeedback] = useState<Record<string, string>>({});
  const [openId, setOpenId] = useState<string | null>(null);
  const [sideTab, setSideTab] = useState<'steps' | 'assets'>('steps');
  const [assetName, setAssetName] = useState<string | null>(null);
  const [assetBody, setAssetBody] = useState<string>('');
  const [rawAssetBody, setRawAssetBody] = useState<string>('');
  const [assetBusy, setAssetBusy] = useState(false);
  const [printable, setPrintable] = useState<{
    title: string;
    projectName: string;
    brand: string;
    filename: string;
    date: string;
    content: string;
  } | null>(null);
  const [filterTab, setFilterTab] = useState<'all' | 'active' | 'waiting' | 'completed'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [wrapStagesMap, setWrapStagesMap] = useState<Record<string, boolean>>({});
  const [durationDraft, setDurationDraft] = useState<Record<string, number>>({});
  const [savingDuration, setSavingDuration] = useState<string | null>(null);
  const poll = useRef<number | null>(null);

  // Produce Video (BuzzcafAI -> BuzzEdit bridge, app/api/produce_api.py).
  const [recordingPath, setRecordingPath] = useState<Record<string, string>>({});
  const [overrideGenre, setOverrideGenre] = useState<Record<string, string>>({});
  const [overrideCoverage, setOverrideCoverage] = useState<Record<string, number>>({});
  const [produceStatus, setProduceStatus] = useState<Record<string, ProduceVideoStatus>>({});
  const [producingId, setProducingId] = useState<string | null>(null);
  const producePoll = useRef<number | null>(null);
  const [teleprompterId, setTeleprompterId] = useState<string | null>(null);
  const [teleprompterText, setTeleprompterText] = useState('');
  const [teleprompterBusy, setTeleprompterBusy] = useState(false);

  useEffect(() => () => {
    if (poll.current) window.clearInterval(poll.current);
    if (producePoll.current) window.clearInterval(producePoll.current);
  }, []);

  const open = useMemo(() => projects.find((p) => p.id === openId) || null, [projects, openId]);
  const openWorkflow = useMemo(
    () => (open ? workflows.find((w) => (w.id || w.name) === open.workflow_name) || null : null),
    [open, workflows],
  );

  const toggleSelect = (projectId: string) => {
    if (openId === projectId) {
      setOpenId(null);
    } else {
      setOpenId(projectId);
      setAssetName(null);
      setAssetBody('');
      setRawAssetBody('');
    }
  };

  const showAsset = async (project: Project, name: string) => {
    setAssetName(name);
    setAssetBusy(true);
    setAssetBody('');
    setRawAssetBody('');
    try {
      const data = await getJson<Record<string, unknown>>(
        `/api/projects/${encodeURIComponent(project.id)}/asset/${encodeURIComponent(name)}`,
      );
      // Text assets come back as {content}; a .json asset comes back parsed.
      const isText = typeof data?.content === 'string';
      const raw = isText ? (data.content as string) : JSON.stringify(data, null, 2);
      const content = isText ? (data.content as string) : `\`\`\`json\n${raw}\n\`\`\``;
      setRawAssetBody(raw);
      setAssetBody(content);
    } catch (err) {
      setAssetBody('');
      setRawAssetBody('');
      toast(describeError(err), 'error');
    } finally {
      setAssetBusy(false);
    }
  };

  const saveArtifact = (filename: string, content: string, project?: Project | null) => {
    if (!content) {
      toast('No content to save.', 'info');
      return;
    }
    try {
      const cleanProj = (project?.name || project?.id || 'buzzcaf_project')
        .toLowerCase()
        .replace(/[^a-z0-9_-]/g, '_')
        .replace(/_+/g, '_');
      const baseFilename = filename || 'artifact.txt';
      const downloadName = baseFilename.toLowerCase().includes(cleanProj)
        ? baseFilename
        : `${cleanProj}_${baseFilename}`;
      const isJson = downloadName.endsWith('.json');
      const mimeType = isJson ? 'application/json;charset=utf-8' : 'text/markdown;charset=utf-8';
      const blob = new Blob([content], { type: mimeType });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = downloadName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast(`Saved "${downloadName}"`, 'success');
    } catch (err) {
      toast(`Could not save file: ${describeError(err)}`, 'error');
    }
  };

  const printArtifact = (title: string, filename: string, content: string, project?: Project | null) => {
    if (!content) {
      toast('No content to print.', 'info');
      return;
    }
    try {
      setPrintable({
        title,
        projectName: project?.name || 'Buzzcaf Project',
        brand: project?.brand || 'Buzzcaf Media',
        filename,
        date: new Date().toLocaleString(),
        content,
      });
      toast('Opening print preview… (Tip: press Ctrl+Shift+P for Windows system printers)', 'info');
      // Allow state update to populate #buzzcaf-printable-artifact on document.body
      setTimeout(() => {
        window.print();
      }, 150);
    } catch (err) {
      toast(`Could not start print: ${describeError(err)}`, 'error');
    }
  };

  const openBrowserPrint = async (projectId: string, name: string) => {
    try {
      await postJson(`/api/projects/${encodeURIComponent(projectId)}/asset/${encodeURIComponent(name)}/open_browser_print`, {});
      toast('Opened in default browser with full printer detection.', 'success');
    } catch {
      window.open(`/api/projects/${encodeURIComponent(projectId)}/asset/${encodeURIComponent(name)}/print?auto=1`, '_blank');
      toast('Opened in default browser with full printer detection.', 'success');
    }
  };

  const toggleAllowAll = async (project: Project) => {
    try {
      const updated = await postJson<Project>(`/api/projects/${encodeURIComponent(project.id)}/toggle_allow_all`, {});
      const isNow = Boolean(updated.metadata?.allow_all);
      toast(`Allow All ${isNow ? 'enabled' : 'disabled'} for "${project.name}".`, 'info');
      await refreshProjects();
    } catch (err) {
      toast(`Failed to toggle Allow All: ${describeError(err)}`, 'error');
    }
  };

  const saveDuration = async (proj: Project) => {
    const raw = durationDraft[proj.id];
    const minutes = raw == null || Number.isNaN(raw) || raw <= 0 ? null : raw;
    setSavingDuration(proj.id);
    try {
      await postJson(`/api/projects/${encodeURIComponent(proj.id)}/duration`, { minutes });
      toast(`Target length updated for "${proj.name}".`, 'success');
      await refreshProjects();
    } catch (err) {
      toast(`Could not update target length: ${describeError(err)}`, 'error');
    } finally {
      setSavingDuration(null);
    }
  };

  const handleDeleteProject = async (proj: Project, e?: React.MouseEvent) => {
    e?.stopPropagation();
    if (deletingId || runningId === proj.id) return;
    const ok = await confirm({
      title: `Delete "${proj.name}"?`,
      body: `This permanently deletes the project directory, scripts, and research assets for "${proj.name}". This cannot be undone.`,
      confirmLabel: 'Delete Project',
      danger: true,
    });
    if (!ok) return;

    setDeletingId(proj.id);
    try {
      await deleteJson(`/api/projects/${encodeURIComponent(proj.id)}`);
      toast(`Project "${proj.name}" deleted.`, 'success');
      if (openId === proj.id) {
        setOpenId(null);
        setAssetName(null);
        setAssetBody('');
        setRawAssetBody('');
      }
      await refreshProjects();
    } catch (err) {
      toast(`Could not delete project: ${describeError(err)}`, 'error');
    } finally {
      setDeletingId(null);
    }
  };

  const run = async (
    project: Project,
    mode: 'execute' | 'approve' | 'allow_all' | 'run_all',
    notes?: string,
    allowAll?: boolean,
  ) => {
    if (runningId) return;
    setRunningId(project.id);
    let startMsg = 'Starting the next workflow step…';
    if (mode === 'approve') startMsg = allowAll ? 'Allowing all steps and continuing…' : 'Approving the step that is waiting…';
    else if (mode === 'allow_all') startMsg = 'Enabling Allow All and continuing…';
    else if (mode === 'run_all') startMsg = 'Running all remaining workflow steps…';
    setLog([startMsg]);
    poll.current = window.setInterval(async () => {
      try {
        const lines = await getJson<string[]>(`/api/projects/${encodeURIComponent(project.id)}/logs`);
        if (Array.isArray(lines) && lines.length) setLog(lines);
      } catch {
        // keep the last log we had
      }
    }, 700);
    try {
      const endpoint = `/api/projects/${encodeURIComponent(project.id)}/${mode === 'allow_all' ? 'allow_all' : mode === 'run_all' ? 'run_all' : mode}`;
      const payload: Record<string, unknown> = {};
      if (notes) payload.feedback = notes;
      if (allowAll) payload.allow_all = true;

      const updated = await postJson<Project>(
        endpoint,
        payload,
        { signal: AbortSignal.timeout(600_000) },
      );
      const step = lastStep(updated);
      if (step?.status === 'paused_for_approval') toast(`${step.step_name || 'The step'} is waiting for your approval.`, 'info');
      else if (updated.status === 'completed') toast(`${project.name} is complete.`, 'success');
      else if (allowAll || mode === 'allow_all') toast(`Allow All enabled: ran ${step?.step_name || 'the next step'}.`, 'success');
      else toast(`Ran ${step?.step_name || 'the next step'}.`, 'success');
      setFeedback((prev) => ({ ...prev, [project.id]: '' }));
    } catch (err) {
      const detail = err instanceof ApiError && err.status === 409
        ? `${describeError(err)} Refreshing the list.`
        : describeError(err);
      setLog((prev) => [...prev, `[ERROR] ${detail}`]);
      toast(detail, 'error');
    } finally {
      if (poll.current) window.clearInterval(poll.current);
      poll.current = null;
      try {
        const lines = await getJson<string[]>(`/api/projects/${encodeURIComponent(project.id)}/logs`);
        if (Array.isArray(lines) && lines.length) setLog(lines);
      } catch {
        // ignore
      }
      await refreshProjects();
      setRunningId(null);
    }
  };

  const pollProduceStatus = (project: Project) => {
    if (producePoll.current) window.clearInterval(producePoll.current);
    producePoll.current = window.setInterval(async () => {
      try {
        const status = await getJson<ProduceVideoStatus>(
          `/api/projects/${encodeURIComponent(project.id)}/produce_video/status`,
        );
        setProduceStatus((prev) => ({ ...prev, [project.id]: status }));
        if (status.state === 'ready' || status.state === 'failed') {
          if (producePoll.current) window.clearInterval(producePoll.current);
          producePoll.current = null;
          setProducingId(null);
          if (status.state === 'ready') toast(`${project.name}: video ready.`, 'success');
          else toast(`${project.name}: ${status.error || 'video production failed.'}`, 'error');
          await refreshProjects();
        }
      } catch {
        // keep the last status we had; the next tick tries again
      }
    }, 3000);
  };

  const produceVideo = async (project: Project) => {
    const path = (recordingPath[project.id] || '').trim();
    if (!path) {
      toast('Enter the absolute path to your recording first.', 'error');
      return;
    }
    if (producingId) return;
    setProducingId(project.id);
    const overrides: Record<string, unknown> = {};
    if (overrideGenre[project.id]) overrides.genre = overrideGenre[project.id];
    if (overrideCoverage[project.id] != null) overrides.target_coverage = overrideCoverage[project.id];
    try {
      await postJson(`/api/projects/${encodeURIComponent(project.id)}/produce_video`, {
        recording_path: path,
        settings_override: Object.keys(overrides).length ? overrides : undefined,
      });
      setProduceStatus((prev) => ({ ...prev, [project.id]: { state: 'starting', message: 'Queued...' } }));
      toast(`Producing video for "${project.name}"...`, 'info');
      pollProduceStatus(project);
    } catch (err) {
      setProducingId(null);
      toast(`Could not start video production: ${describeError(err)}`, 'error');
    }
  };

  const openTeleprompter = async (project: Project) => {
    setTeleprompterId(project.id);
    setTeleprompterBusy(true);
    setTeleprompterText('');
    try {
      const data = await getJson<Record<string, unknown>>(
        `/api/projects/${encodeURIComponent(project.id)}/asset/buzzedit_script`,
      );
      setTeleprompterText(typeof data?.content === 'string' ? data.content : '');
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setTeleprompterBusy(false);
    }
  };

  // Filtered and searched projects
  const counts = useMemo(() => {
    let waiting = 0;
    let completed = 0;
    let active = 0;
    for (const p of projects) {
      const step = lastStep(p);
      if (step?.status === 'paused_for_approval') {
        waiting++;
      } else if (p.status === 'completed') {
        completed++;
      } else {
        active++;
      }
    }
    return { all: projects.length, active, waiting, completed };
  }, [projects]);

  const filteredProjects = useMemo(() => {
    return projects.filter((p) => {
      const step = lastStep(p);
      const isWaiting = step?.status === 'paused_for_approval';
      const isCompleted = p.status === 'completed';

      if (filterTab === 'active' && (isCompleted || isWaiting)) return false;
      if (filterTab === 'waiting' && !isWaiting) return false;
      if (filterTab === 'completed' && !isCompleted) return false;

      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase().trim();
        const matchName = p.name?.toLowerCase().includes(q);
        const matchBrand = p.brand?.toLowerCase().includes(q);
        const matchWf = p.workflow_name?.toLowerCase().includes(q);
        const matchId = p.id?.toLowerCase().includes(q);
        if (!matchName && !matchBrand && !matchWf && !matchId) return false;
      }
      return true;
    });
  }, [projects, filterTab, searchQuery]);

  return (
    <div>
      {/* Top Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20, flexWrap: 'wrap', gap: 16 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: '1.5rem', color: 'var(--text-primary)' }}>Projects</h2>
          <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: 4 }}>
            Monitor pipelines, review stage progressions, and control autonomous execution
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button type="button" className="btn btn-outline" onClick={() => refreshProjects()}>
            <RotateCw size={15} />
            <span>Refresh</span>
          </button>
        </div>
      </div>

      {/* Filter Tabs & Search Bar */}
      <div className="project-filter-tabs">
        <button
          type="button"
          className={`project-filter-tab ${filterTab === 'all' ? 'active' : ''}`}
          onClick={() => setFilterTab('all')}
        >
          <Layers size={14} />
          <span>All Projects</span>
          <span className="tab-count">{counts.all}</span>
        </button>
        <button
          type="button"
          className={`project-filter-tab ${filterTab === 'active' ? 'active' : ''}`}
          onClick={() => setFilterTab('active')}
        >
          <Play size={14} />
          <span>Active / In Progress</span>
          <span className="tab-count">{counts.active}</span>
        </button>
        <button
          type="button"
          className={`project-filter-tab ${filterTab === 'waiting' ? 'active' : ''}`}
          onClick={() => setFilterTab('waiting')}
        >
          <Clock size={14} />
          <span>Needs Approval</span>
          <span className="tab-count">{counts.waiting}</span>
        </button>
        <button
          type="button"
          className={`project-filter-tab ${filterTab === 'completed' ? 'active' : ''}`}
          onClick={() => setFilterTab('completed')}
        >
          <CheckCircle2 size={14} />
          <span>Completed</span>
          <span className="tab-count">{counts.completed}</span>
        </button>

        {/* Search input */}
        <div className="project-search-container">
          <Search size={14} style={{ position: 'absolute', left: 10, color: 'var(--text-muted)' }} />
          <input
            type="text"
            className="form-control project-search-input"
            placeholder="Search projects, channels..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              paddingLeft: 32,
              paddingRight: 10,
              paddingTop: 6,
              paddingBottom: 6,
              fontSize: '0.82rem',
              borderRadius: 8,
              height: 34,
            }}
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery('')}
              style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex', marginLeft: -26, zIndex: 2 }}
            >
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      {/* Empty State */}
      {projects.length === 0 && (
        <div className="panel-card" style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: 40 }}>
          <p style={{ margin: 0, fontSize: '1rem' }}>{health === 'offline' ? 'The Studio backend is offline.' : 'No projects yet.'}</p>
          <p style={{ fontSize: '0.85rem', marginTop: 6 }}>Create one from the Dashboard, send a topic from the Vault, or ask Dexter to start one.</p>
        </div>
      )}

      {projects.length > 0 && filteredProjects.length === 0 && (
        <div className="panel-card" style={{ textAlign: 'center', color: 'var(--text-secondary)', padding: 32 }}>
          <Filter size={24} style={{ color: 'var(--text-muted)', marginBottom: 8 }} />
          <p style={{ margin: 0, fontSize: '0.95rem' }}>No projects match the selected tab or search filter.</p>
          <button type="button" className="btn btn-outline btn-sm" onClick={() => { setFilterTab('all'); setSearchQuery(''); }} style={{ marginTop: 12 }}>
            Reset Filters
          </button>
        </div>
      )}

      {/* Main Workspace Layout: Cards List + Optional Side Drawer */}
      <div className="projects-layout">
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="project-list">
            {filteredProjects.map((proj) => {
              const step = lastStep(proj);
              const waiting = step?.status === 'paused_for_approval';
              const busy = runningId === proj.id;
              const isAllowAll = Boolean(proj.metadata?.allow_all);
              const isOpen = openId === proj.id;
              const isWrapStages = Boolean(wrapStagesMap[proj.id]);

              // Workflow & Stages Pipeline computation
              const wf = workflows.find((w) => (w.id || w.name) === proj.workflow_name);
              const steps = wf?.steps || [];
              const stepsWithState = steps.map((s, idx) => ({
                step: s,
                index: idx + 1,
                state: stepState(proj, s),
              }));
              const completedCount = stepsWithState.filter((s) => s.state === 'done').length;
              const totalCount = steps.length;
              const currentStepItem = stepsWithState.find((s) => s.state === 'current' || s.state === 'waiting');
              const progressPercent = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : (proj.status === 'completed' ? 100 : 0);

              return (
                <div
                  key={proj.id}
                  className="project-item"
                  style={{
                    borderColor: isOpen ? 'var(--accent-primary)' : undefined,
                    boxShadow: isOpen ? '0 0 0 1px var(--accent-primary), var(--card-shadow)' : undefined,
                  }}
                >
                  {/* Top Card Row: Title, Badges & Quick Action Controls */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 14, flexWrap: 'wrap' }}>
                    <div style={{ flex: 1, minWidth: 260 }}>
                      <div
                        className="project-name"
                        onClick={() => toggleSelect(proj.id)}
                        role="button"
                        tabIndex={0}
                        onKeyDown={(e) => e.key === 'Enter' && toggleSelect(proj.id)}
                        style={{ cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 8 }}
                      >
                        <span>{proj.name}</span>
                        <span style={{ fontSize: '0.75rem', color: 'var(--accent-primary)', fontWeight: 500, display: 'inline-flex', alignItems: 'center' }}>
                          {isOpen ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
                        </span>
                      </div>

                      {/* Header Badges Row */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 6, flexWrap: 'wrap' }}>
                        {/* Status Badge */}
                        <span className={`status-badge-inline status-${waiting ? 'waiting' : proj.status}`}>
                          {waiting ? (
                            <>
                              <Clock size={11} />
                              <span>Awaiting Approval</span>
                            </>
                          ) : proj.status === 'completed' ? (
                            <>
                              <CheckCircle2 size={11} />
                              <span>Completed</span>
                            </>
                          ) : (
                            <>
                              <Play size={10} />
                              <span>{String(proj.status || 'active').toUpperCase()}</span>
                            </>
                          )}
                        </span>

                        {/* Brand Badge */}
                        <span className="brand-badge">{proj.brand}</span>

                        {/* Allow All Toggle Badge */}
                        <button
                          type="button"
                          className="btn btn-outline"
                          onClick={(e) => { e.stopPropagation(); toggleAllowAll(proj); }}
                          title={isAllowAll ? 'Allow All is ON: steps run automatically without pausing. Click to turn off.' : 'Click to enable Allow All: steps advance without pausing for approval.'}
                          style={{
                            padding: '3px 8px',
                            fontSize: '0.74rem',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 4,
                            borderRadius: 6,
                            borderColor: isAllowAll ? '#10b981' : 'var(--border-card)',
                            background: isAllowAll ? 'rgba(16, 185, 129, 0.15)' : 'var(--bg-pill)',
                            color: isAllowAll ? '#34d399' : 'var(--text-secondary)',
                          }}
                        >
                          {isAllowAll ? <CheckCircle2 size={12} style={{ color: '#10b981' }} /> : <ShieldAlert size={12} />}
                          <span>{isAllowAll ? 'Allow All: ON' : 'Allow All: OFF'}</span>
                        </button>
                      </div>
                    </div>

                    {/* Actions Group on Top Right */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginLeft: 'auto' }}>
                      {waiting ? (
                        <>
                          <button
                            type="button"
                            className="btn btn-outline"
                            disabled={!!runningId}
                            onClick={() => run(proj, 'approve')}
                            style={{ padding: '6px 12px', fontSize: '0.8rem' }}
                            title="Approve this step and pause again at the next approval step"
                          >
                            <CheckCircle2 size={13} />
                            <span>Approve</span>
                          </button>
                          <button
                            type="button"
                            className="btn"
                            disabled={!!runningId}
                            onClick={() => run(proj, 'approve', undefined, true)}
                            style={{
                              padding: '6px 14px',
                              fontSize: '0.8rem',
                              background: 'linear-gradient(135deg, #10b981, #059669)',
                              borderColor: '#059669',
                              color: '#ffffff',
                              fontWeight: 600,
                            }}
                            title="Approve this step and enable Allow All so future steps run continuously"
                          >
                            <CheckCheck size={14} />
                            <span>Allow all & continue</span>
                          </button>
                        </>
                      ) : (
                        proj.status !== 'completed' && (
                          <>
                            <button
                              type="button"
                              className="btn"
                              disabled={!!runningId}
                              onClick={() => run(proj, 'execute')}
                              style={{ padding: '6px 14px', fontSize: '0.8rem' }}
                            >
                              <Play size={13} />
                              <span>{busy ? 'Running…' : 'Run next step'}</span>
                            </button>
                            {isAllowAll && (
                              <button
                                type="button"
                                className="btn btn-outline"
                                disabled={!!runningId}
                                onClick={() => run(proj, 'run_all')}
                                style={{ padding: '6px 12px', fontSize: '0.8rem', borderColor: '#10b981', color: '#34d399' }}
                                title="Run automatically through all remaining steps to completion"
                              >
                                <FastForward size={13} />
                                <span>Run all</span>
                              </button>
                            )}
                          </>
                        )
                      )}

                      {/* Inspect / Drawer Toggle Button */}
                      <button
                        type="button"
                        className={`btn btn-sm ${isOpen ? '' : 'btn-outline'}`}
                        onClick={() => toggleSelect(proj.id)}
                        style={{
                          padding: '6px 11px',
                          fontSize: '0.78rem',
                          background: isOpen ? 'var(--accent-gradient)' : 'transparent',
                          color: isOpen ? 'var(--text-on-accent)' : 'var(--text-secondary)',
                          borderColor: isOpen ? 'transparent' : 'var(--border-card)',
                        }}
                        title={isOpen ? 'Collapse details panel' : 'Inspect project details, full timeline & assets'}
                      >
                        <span>{isOpen ? 'Close' : 'Details'}</span>
                        {isOpen ? <X size={12} /> : <ChevronRight size={12} />}
                      </button>

                      {/* Delete Project Button */}
                      <button
                        type="button"
                        className="btn btn-outline btn-sm"
                        onClick={(e) => handleDeleteProject(proj, e)}
                        disabled={deletingId === proj.id || runningId === proj.id}
                        title={`Delete project "${proj.name}"`}
                        style={{
                          padding: '6px 9px',
                          fontSize: '0.78rem',
                          borderColor: 'rgba(239, 68, 68, 0.35)',
                          color: '#f87171',
                          background: 'transparent',
                        }}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </div>

                  {/* Metadata Row: Workflow, Stage, ID */}
                  <div className="project-meta">
                    <span>
                      Workflow: <code style={{ color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>{proj.workflow_name}</code>
                    </span>
                    <span>
                      Stage:{' '}
                      <strong
                        style={{
                          color: currentStepItem?.state === 'waiting' ? '#c4b5fd' : currentStepItem?.state === 'current' ? '#fbbf24' : 'var(--text-primary)',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {proj.current_step ? proj.current_step : proj.status === 'completed' ? 'All stages complete' : 'Ready'}
                      </strong>
                    </span>
                    <span title={proj.id}>
                      ID: <code style={{ color: 'var(--text-muted)' }}>{formatProjectId(proj.id)}</code>
                      <CopyButton text={proj.id} />
                    </span>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }} title="Target script runtime; change it, save, then re-run the Script step to resize">
                      Target length:
                      <input
                        type="number"
                        className="form-control"
                        min={0.5}
                        max={180}
                        step={0.5}
                        placeholder="min"
                        value={durationDraft[proj.id] ?? (typeof proj.metadata?.target_duration_minutes === 'number' ? proj.metadata.target_duration_minutes : '')}
                        onChange={(e) => setDurationDraft((prev) => ({ ...prev, [proj.id]: Number(e.target.value) }))}
                        style={{ width: 64, padding: '2px 6px', fontSize: '0.78rem', height: 26 }}
                      />
                      <button
                        type="button"
                        className="btn btn-outline btn-sm"
                        disabled={savingDuration === proj.id}
                        onClick={() => saveDuration(proj)}
                        style={{ padding: '3px 8px', fontSize: '0.74rem' }}
                      >
                        {savingDuration === proj.id ? 'Saving…' : 'Save'}
                      </button>
                    </span>
                  </div>

                  {/* =========================================================
                      THE STAGES GLIMPSE: Complete Visual Pipeline Overview
                      ========================================================= */}
                  <div className="stages-glimpse-container">
                    <div className="stages-glimpse-header">
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                          Stages Pipeline:
                        </span>
                        <span>
                          {totalCount > 0 ? (
                            <>
                              <strong style={{ color: progressPercent === 100 ? '#34d399' : 'var(--accent-primary)' }}>
                                {completedCount} of {totalCount} completed
                              </strong>{' '}
                              ({progressPercent}%)
                            </>
                          ) : (
                            <span>{proj.status === 'completed' ? 'Completed' : 'Active'}</span>
                          )}
                        </span>
                        {currentStepItem && (
                          <span style={{ color: currentStepItem.state === 'waiting' ? '#c4b5fd' : '#fbbf24', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                            <span className="stage-pulse-beacon" style={{ backgroundColor: currentStepItem.state === 'waiting' ? '#a78bfa' : '#f59e0b' }} />
                            <span>
                              Active: <strong>{currentStepItem.index}. {currentStepItem.step.name}</strong> ({currentStepItem.step.agent_role})
                            </span>
                          </span>
                        )}
                      </div>

                      {totalCount > 6 && (
                        <button
                          type="button"
                          onClick={() => setWrapStagesMap((prev) => ({ ...prev, [proj.id]: !prev[proj.id] }))}
                          style={{
                            background: 'none',
                            border: 'none',
                            color: 'var(--accent-primary)',
                            fontSize: '0.74rem',
                            cursor: 'pointer',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 3,
                            padding: '2px 6px',
                            borderRadius: 4,
                          }}
                        >
                          <span>{isWrapStages ? 'Single Row' : `View All (${totalCount})`}</span>
                        </button>
                      )}
                    </div>

                    {/* Progress Bar */}
                    <div className="stages-progress-bar-bg">
                      <div
                        className="stages-progress-bar-fill"
                        style={{
                          width: `${progressPercent}%`,
                          background:
                            progressPercent === 100
                              ? '#10b981'
                              : 'linear-gradient(90deg, #10b981, #3b82f6, #a78bfa)',
                        }}
                      />
                    </div>

                    {/* Glimpse of all stages (Interactive nodes) */}
                    {stepsWithState.length > 0 ? (
                      <div className={`stages-track ${isWrapStages ? 'wrap-mode' : ''}`}>
                        {stepsWithState.map((s) => {
                          const isAutoApproved = Boolean(proj.metadata?.allow_all) && s.step.requires_approval;
                          return (
                            <div
                              key={s.step.name}
                              className={`stage-pill stage-${s.state}`}
                              onClick={() => {
                                setOpenId(proj.id);
                                setSideTab('steps');
                              }}
                              title={`Stage ${s.index}: ${s.step.name}\nAgent: ${s.step.agent_role}\nStatus: ${s.state.toUpperCase()}${
                                s.step.requires_approval ? (isAutoApproved ? ' (Auto-approved via Allow All)' : ' (Needs Approval)') : ''
                              }${s.step.description ? `\n\n${s.step.description}` : ''}\n\nClick to inspect in detail.`}
                            >
                              {s.state === 'done' ? (
                                <CheckCircle2 size={12} style={{ color: '#34d399' }} />
                              ) : s.state === 'current' ? (
                                <span className="stage-pulse-beacon" />
                              ) : s.state === 'waiting' ? (
                                <Clock size={12} style={{ color: '#c4b5fd' }} />
                              ) : s.state === 'failed' ? (
                                <AlertCircle size={12} style={{ color: '#f87171' }} />
                              ) : (
                                <Circle size={8} style={{ color: 'var(--text-muted)' }} />
                              )}
                              <span>
                                {s.index}. {s.step.name}
                              </span>
                              {s.step.requires_approval && s.state !== 'done' && (
                                <span
                                  style={{
                                    fontSize: '0.65rem',
                                    color: isAutoApproved ? '#34d399' : 'var(--accent-primary)',
                                    opacity: 0.9,
                                  }}
                                  title={isAutoApproved ? 'Auto-approved' : 'Approval Gate'}
                                >
                                  {isAutoApproved ? '⚡' : '🔒'}
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                        Workflow definition <code>{proj.workflow_name}</code> loaded with custom steps.
                      </div>
                    )}
                  </div>

                  {/* Waiting for approval notes input */}
                  {waiting && (
                    <div style={{ width: '100%', display: 'flex', gap: 10, alignItems: 'center', marginTop: 4 }}>
                      <input
                        type="text"
                        className="form-control"
                        placeholder={`Revision notes for ${step?.step_name || 'this step'} (optional)`}
                        value={feedback[proj.id] || ''}
                        onChange={(e) => setFeedback((prev) => ({ ...prev, [proj.id]: e.target.value }))}
                      />
                      <button
                        type="button"
                        className="btn btn-outline"
                        disabled={!!runningId || !(feedback[proj.id] || '').trim()}
                        onClick={() => run(proj, 'execute', feedback[proj.id])}
                        style={{ whiteSpace: 'nowrap' }}
                      >
                        <span>Revise with notes</span>
                      </button>
                    </div>
                  )}

                  {/* Busy live log viewer */}
                  {busy && (
                    <div style={{ width: '100%' }}>
                      <div className="logs-panel">
                        {log.map((line, i) => <div key={i}>{line}</div>)}
                      </div>
                    </div>
                  )}

                  {/* ===================================================
                      PRODUCE VIDEO: the BuzzcafAI -> BuzzEdit bridge.
                      Needs a finished script AND the structured visual plan.
                      =================================================== */}
                  {Boolean(proj.assets?.script) && Boolean(proj.assets?.visual_plan) && (() => {
                    const status = produceStatus[proj.id];
                    const producing = producingId === proj.id || status?.state === 'starting' || status?.state === 'running';
                    return (
                      <div className="stages-glimpse-container" style={{ marginTop: 4 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
                          <Video size={14} style={{ color: 'var(--accent-primary)' }} />
                          <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '0.85rem' }}>
                            Produce Video (BuzzEdit)
                          </span>
                          {proj.assets?.buzzedit_script && (
                            <button
                              type="button"
                              className="btn btn-outline btn-sm"
                              onClick={() => openTeleprompter(proj)}
                              style={{ marginLeft: 'auto', padding: '3px 10px', fontSize: '0.74rem' }}
                              title="Read the BuzzEdit-annotated script full screen"
                            >
                              <Maximize2 size={12} />
                              <span>Teleprompter</span>
                            </button>
                          )}
                        </div>

                        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
                          <div style={{ position: 'relative', flex: '1 1 260px', minWidth: 220 }}>
                            <Mic size={13} style={{ position: 'absolute', left: 9, top: 10, color: 'var(--text-muted)' }} />
                            <input
                              type="text"
                              className="form-control"
                              placeholder="Absolute path to your recording (e.g. C:\Recordings\take1.mp4)"
                              value={recordingPath[proj.id] || ''}
                              onChange={(e) => setRecordingPath((prev) => ({ ...prev, [proj.id]: e.target.value }))}
                              disabled={producing}
                              style={{ paddingLeft: 28, fontSize: '0.8rem', height: 32 }}
                            />
                          </div>
                          <select
                            className="form-control"
                            value={overrideGenre[proj.id] || genreForBrand(proj.brand)}
                            onChange={(e) => setOverrideGenre((prev) => ({ ...prev, [proj.id]: e.target.value }))}
                            disabled={producing}
                            title="Genre override (defaults to the brand's mapped genre)"
                            style={{ width: 140, fontSize: '0.78rem', height: 32 }}
                          >
                            {['documentary', 'horror', 'true_crime', 'comedy', 'general'].map((g) => (
                              <option key={g} value={g}>{g}</option>
                            ))}
                          </select>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }} title="Target B-roll coverage (BuzzEdit caps at 80%)">
                            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>Coverage</span>
                            <input
                              type="range"
                              min={0}
                              max={80}
                              step={5}
                              value={Math.round((overrideCoverage[proj.id] ?? 0.6) * 100)}
                              onChange={(e) => setOverrideCoverage((prev) => ({ ...prev, [proj.id]: Number(e.target.value) / 100 }))}
                              disabled={producing}
                              style={{ width: 90 }}
                            />
                            <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', width: 32 }}>
                              {Math.round((overrideCoverage[proj.id] ?? 0.6) * 100)}%
                            </span>
                          </div>
                          <button
                            type="button"
                            className="btn"
                            disabled={producing || !!runningId}
                            onClick={() => produceVideo(proj)}
                            style={{ padding: '6px 14px', fontSize: '0.8rem', whiteSpace: 'nowrap' }}
                          >
                            <Video size={13} />
                            <span>{producing ? 'Producing…' : 'Produce Video'}</span>
                          </button>
                        </div>

                        {status && status.state !== 'idle' && (
                          <div style={{ marginTop: 10 }}>
                            <div className="stages-progress-bar-bg">
                              <div
                                className="stages-progress-bar-fill"
                                style={{
                                  width: `${Math.round((status.progress || 0) * 100)}%`,
                                  background: status.state === 'failed'
                                    ? '#ef4444'
                                    : status.state === 'ready'
                                      ? '#10b981'
                                      : 'linear-gradient(90deg, #10b981, #3b82f6, #a78bfa)',
                                }}
                              />
                            </div>
                            <div style={{ fontSize: '0.76rem', color: status.state === 'failed' ? '#f87171' : 'var(--text-secondary)', marginTop: 6 }}>
                              {status.state === 'failed'
                                ? `Failed: ${status.error || 'unknown error'}`
                                : status.message || status.state}
                            </div>
                            {status.state === 'ready' && status.output_path && (
                              <div style={{ fontSize: '0.76rem', color: 'var(--text-primary)', marginTop: 6, wordBreak: 'break-all' }}>
                                Rendered file (on BuzzEdit's machine): <code>{status.output_path}</code>
                                <CopyButton text={status.output_path} label="Copy output path" />
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })()}
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Side Drawer for Selected Project */}
        {open && (
          <div className="panel-card project-detail-drawer">
            {/* Drawer Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0, fontSize: '1.15rem' }}>
                  {open.name}
                </h3>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span>{open.brand}</span>
                  <span>·</span>
                  <code>{open.workflow_name}</code>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <button
                  type="button"
                  className="btn btn-outline btn-sm"
                  onClick={(e) => handleDeleteProject(open, e)}
                  disabled={deletingId === open.id || runningId === open.id}
                  title={`Delete project "${open.name}"`}
                  style={{
                    padding: '4px 8px',
                    fontSize: '0.75rem',
                    borderColor: 'rgba(239, 68, 68, 0.4)',
                    color: '#f87171',
                    background: 'transparent',
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 4,
                  }}
                >
                  <Trash2 size={13} />
                  <span>{deletingId === open.id ? 'Deleting…' : 'Delete'}</span>
                </button>
                <button
                  type="button"
                  onClick={() => setOpenId(null)}
                  aria-label="Close panel"
                  style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', display: 'flex', padding: 4 }}
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Allow All mode card in side panel */}
            <div
              style={{
                marginTop: 14,
                marginBottom: 16,
                padding: '10px 14px',
                borderRadius: 8,
                backgroundColor: Boolean(open.metadata?.allow_all) ? 'rgba(16, 185, 129, 0.1)' : 'var(--bg-pill)',
                border: `1px solid ${Boolean(open.metadata?.allow_all) ? 'rgba(16, 185, 129, 0.3)' : 'var(--border-card)'}`,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: 12,
              }}
            >
              <div>
                <div style={{ fontSize: '0.85rem', fontWeight: 600, color: Boolean(open.metadata?.allow_all) ? '#34d399' : 'var(--text-primary)' }}>
                  Allow All Mode: {Boolean(open.metadata?.allow_all) ? 'Enabled' : 'Disabled'}
                </div>
                <div style={{ fontSize: '0.74rem', color: 'var(--text-secondary)' }}>
                  {Boolean(open.metadata?.allow_all)
                    ? 'Steps advance automatically without pausing for approval.'
                    : 'Steps will pause at approval gates.'}
                </div>
              </div>
              <button
                type="button"
                className={`btn btn-sm ${Boolean(open.metadata?.allow_all) ? 'btn-outline' : ''}`}
                onClick={() => toggleAllowAll(open)}
                style={{
                  fontSize: '0.76rem',
                  padding: '4px 10px',
                  borderColor: Boolean(open.metadata?.allow_all) ? '#10b981' : 'var(--border-card)',
                  color: Boolean(open.metadata?.allow_all) ? '#34d399' : 'var(--text-on-accent)',
                  background: Boolean(open.metadata?.allow_all) ? 'transparent' : 'var(--accent-gradient)',
                }}
              >
                {Boolean(open.metadata?.allow_all) ? 'Turn Off' : 'Enable Allow All'}
              </button>
            </div>

            {/* Drawer Sub-tabs: Steps Timeline vs Assets */}
            <div style={{ display: 'flex', gap: 6, borderBottom: '1px solid var(--border-card)', paddingBottom: 8, marginBottom: 16 }}>
              <button
                type="button"
                className={`btn btn-sm ${sideTab === 'steps' ? '' : 'btn-outline'}`}
                onClick={() => setSideTab('steps')}
                style={{
                  padding: '5px 12px',
                  fontSize: '0.78rem',
                  background: sideTab === 'steps' ? 'var(--accent-gradient)' : 'transparent',
                  borderColor: sideTab === 'steps' ? 'transparent' : 'var(--border-card)',
                  color: sideTab === 'steps' ? 'var(--text-on-accent)' : 'var(--text-secondary)',
                }}
              >
                <span>Timeline ({openWorkflow?.steps?.length || 0} Stages)</span>
              </button>
              <button
                type="button"
                className={`btn btn-sm ${sideTab === 'assets' ? '' : 'btn-outline'}`}
                onClick={() => setSideTab('assets')}
                style={{
                  padding: '5px 12px',
                  fontSize: '0.78rem',
                  background: sideTab === 'assets' ? 'var(--accent-gradient)' : 'transparent',
                  borderColor: sideTab === 'assets' ? 'transparent' : 'var(--border-card)',
                  color: sideTab === 'assets' ? 'var(--text-on-accent)' : 'var(--text-secondary)',
                }}
              >
                <span>Produced Assets ({Object.keys(open.assets || {}).length})</span>
              </button>
            </div>

            {/* Tab: Steps Timeline */}
            {sideTab === 'steps' && (
              <div>
                {openWorkflow?.steps?.length ? (
                  <div className="timeline-container" style={{ marginTop: 0 }}>
                    {openWorkflow.steps.map((s, i) => {
                      const state = stepState(open, s);
                      const isAutoApproved = Boolean(open.metadata?.allow_all) && s.requires_approval;
                      return (
                        <div
                          key={s.name}
                          className="timeline-step"
                          style={{
                            padding: '10px 14px',
                            gap: 12,
                            borderColor: state === 'pending' ? 'var(--border-card)' : STATE_COLOR[state],
                          }}
                        >
                          <div className="step-num" style={{ color: STATE_COLOR[state] }}>{i + 1}</div>
                          <div style={{ minWidth: 0, flex: 1 }}>
                            <div style={{ color: 'var(--text-primary)', fontSize: '0.88rem', fontWeight: 600 }}>{s.name}</div>
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                              {s.agent_role}
                              {s.requires_approval && (
                                <span style={{ color: isAutoApproved ? '#34d399' : 'var(--accent-primary)' }}>
                                  {isAutoApproved ? ' · auto-approved' : ' · needs approval'}
                                </span>
                              )}
                            </div>
                            {s.description && (
                              <div style={{ fontSize: '0.73rem', color: 'var(--text-muted)', marginTop: 4 }}>
                                {s.description}
                              </div>
                            )}
                          </div>
                          <span style={{ fontSize: '0.72rem', color: STATE_COLOR[state], textTransform: 'uppercase', fontWeight: 700 }}>
                            {state}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: 0 }}>
                    No definition loaded for <code>{open.workflow_name}</code>.
                  </p>
                )}
              </div>
            )}

            {/* Tab: Produced Assets */}
            {sideTab === 'assets' && (
              <div>
                {Object.keys(open.assets || {}).length === 0 ? (
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: 0 }}>
                    No assets produced yet. Run workflow stages to generate script, research, and production notes.
                  </p>
                ) : (
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                    {Object.entries(open.assets || {}).map(([name, file]) => (
                      <button
                        key={name}
                        type="button"
                        onClick={() => showAsset(open, name)}
                        title={file}
                        style={{
                          backgroundColor: assetName === name ? 'var(--bg-card-hover)' : 'var(--bg-pill)',
                          border: `1px solid ${assetName === name ? 'var(--border-highlight)' : 'var(--border-card)'}`,
                          color: 'var(--text-primary)',
                          padding: '6px 12px',
                          borderRadius: 8,
                          fontSize: '0.8rem',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: 6,
                        }}
                      >
                        <FileText size={13} />
                        <span>{name}</span>
                      </button>
                    ))}
                  </div>
                )}

                {assetName && (
                  <div style={{ marginTop: 16, borderTop: '1px solid var(--border-card)', paddingTop: 16 }}>
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: 12,
                        flexWrap: 'wrap',
                        gap: 10,
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0, flex: '1 1 200px' }}>
                        <FileText size={16} style={{ color: 'var(--accent-primary)', flexShrink: 0 }} />
                        <div style={{ minWidth: 0 }}>
                          <div style={{ fontWeight: 600, fontSize: '0.9rem', color: 'var(--text-primary)', textTransform: 'capitalize' }}>
                            {assetName.replace(/_/g, ' ')}
                          </div>
                          <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', wordBreak: 'break-all' }}>
                            {open.assets?.[assetName] || assetName}
                          </div>
                        </div>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                        <button
                          type="button"
                          className="btn btn-outline btn-sm"
                          onClick={() =>
                            printArtifact(
                              assetName.replace(/_/g, ' '),
                              open.assets?.[assetName] || `${assetName}.md`,
                              assetBody,
                              open,
                            )
                          }
                          disabled={assetBusy || !assetBody}
                          title="Print artifact (Press Ctrl+Shift+P in print dialog to select your physical printer)"
                          style={{
                            padding: '4px 11px',
                            fontSize: '0.78rem',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 5,
                            borderRadius: 6,
                          }}
                        >
                          <Printer size={13} />
                          <span>Print</span>
                        </button>
                        <button
                          type="button"
                          className="btn btn-outline btn-sm"
                          onClick={() => openBrowserPrint(open.id, assetName)}
                          disabled={assetBusy || !assetBody}
                          title="Open in your default system browser (Chrome/Edge) to detect all network/local printers"
                          style={{
                            padding: '4px 11px',
                            fontSize: '0.78rem',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 5,
                            borderRadius: 6,
                          }}
                        >
                          <ExternalLink size={13} />
                          <span>Browser Print</span>
                        </button>
                        <button
                          type="button"
                          className="btn btn-outline btn-sm"
                          onClick={() =>
                            saveArtifact(
                              open.assets?.[assetName] || `${assetName}.md`,
                              rawAssetBody || assetBody,
                              open,
                            )
                          }
                          disabled={assetBusy || !assetBody}
                          title="Save artifact file to disk"
                          style={{
                            padding: '4px 11px',
                            fontSize: '0.78rem',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 5,
                            borderRadius: 6,
                          }}
                        >
                          <Download size={13} />
                          <span>Save</span>
                        </button>
                        <CopyButton text={rawAssetBody || assetBody} label="Copy artifact content" />
                      </div>
                    </div>

                    {assetBusy ? (
                      <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Clock size={14} className="spin" /> Loading…
                      </div>
                    ) : assetBody ? (
                      <Markdown text={assetBody} />
                    ) : (
                      <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: 8 }}>
                        <Circle size={12} /> Nothing to show.
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Teleprompter: a full-screen, read-only view of the BuzzEdit-annotated
          script. Directive brackets are left as literal text on purpose --
          the presenter should see `[broll: ...]` cues, not have them hidden
          by Markdown rendering. */}
      {teleprompterId && (
        <div
          role="dialog"
          aria-modal="true"
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(10, 10, 14, 0.96)',
            zIndex: 1000,
            display: 'flex',
            flexDirection: 'column',
            padding: 24,
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 10 }}>
            <span style={{ color: '#e5e7eb', fontSize: '0.85rem', fontWeight: 600 }}>
              Teleprompter — {projects.find((p) => p.id === teleprompterId)?.name || teleprompterId}
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
              {teleprompterText && (
                <>
                  <button
                    type="button"
                    className="btn btn-outline btn-sm"
                    onClick={() => {
                      const proj = projects.find((p) => p.id === teleprompterId);
                      printArtifact('Annotated Script (Teleprompter)', 'buzzedit_script.txt', teleprompterText, proj);
                    }}
                    style={{ color: '#e5e7eb', borderColor: 'rgba(255,255,255,0.3)', padding: '5px 12px', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: 6 }}
                    title="Print script to printer (Press Ctrl+Shift+P for Windows system printers)"
                  >
                    <Printer size={14} />
                    <span>Print</span>
                  </button>
                  <button
                    type="button"
                    className="btn btn-outline btn-sm"
                    onClick={() => {
                      if (teleprompterId) openBrowserPrint(teleprompterId, 'buzzedit_script');
                    }}
                    style={{ color: '#e5e7eb', borderColor: 'rgba(255,255,255,0.3)', padding: '5px 12px', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: 6 }}
                    title="Open in default system browser to detect all printers"
                  >
                    <ExternalLink size={14} />
                    <span>Browser Print</span>
                  </button>
                  <button
                    type="button"
                    className="btn btn-outline btn-sm"
                    onClick={() => {
                      const proj = projects.find((p) => p.id === teleprompterId);
                      saveArtifact('buzzedit_script.txt', teleprompterText, proj);
                    }}
                    style={{ color: '#e5e7eb', borderColor: 'rgba(255,255,255,0.3)', padding: '5px 12px', fontSize: '0.8rem', display: 'inline-flex', alignItems: 'center', gap: 6 }}
                    title="Save script to file"
                  >
                    <Download size={14} />
                    <span>Save</span>
                  </button>
                </>
              )}
              <button
                type="button"
                className="btn btn-outline btn-sm"
                onClick={() => { setTeleprompterId(null); setTeleprompterText(''); }}
                style={{ color: '#e5e7eb', borderColor: 'rgba(255,255,255,0.3)' }}
              >
                <X size={14} />
                <span>Close</span>
              </button>
            </div>
          </div>
          <div style={{ flex: 1, overflowY: 'auto', display: 'flex', justifyContent: 'center' }}>
            {teleprompterBusy ? (
              <div style={{ color: '#9ca3af', fontSize: '1rem', marginTop: 40 }}>Loading…</div>
            ) : (
              <pre
                style={{
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  color: '#f3f4f6',
                  fontFamily: 'inherit',
                  fontSize: '1.6rem',
                  lineHeight: 1.6,
                  maxWidth: 900,
                  margin: 0,
                }}
              >
                {teleprompterText || 'No annotated script yet — produce a video first.'}
              </pre>
            )}
          </div>
        </div>
      )}

      {/* Hidden printable area for artifacts mounted directly on document.body */}
      {printable &&
        createPortal(
          <div id="buzzcaf-printable-artifact" aria-hidden="true">
            <style>
              {`
                @page {
                  margin: 0;
                  size: auto;
                }
              `}
            </style>
            <table className="buzzcaf-print-table">
              <thead>
                <tr>
                  <td className="buzzcaf-print-top-spacer">
                    <div style={{ height: '0.5in', minHeight: '0.5in', maxHeight: '0.5in', lineHeight: '0.5in', fontSize: 1 }}>&nbsp;</div>
                  </td>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td className="buzzcaf-print-content-cell">
                    <div className="printable-artifact-header">
                      <h1>{printable.title}</h1>
                      <div className="printable-artifact-meta">
                        <span><strong>Project:</strong> {printable.projectName}</span>
                        <span><strong>Channel:</strong> {printable.brand}</span>
                        <span><strong>File:</strong> {printable.filename}</span>
                        <span><strong>Printed:</strong> {printable.date}</span>
                      </div>
                    </div>
                    <div className="printable-artifact-content">
                      <Markdown text={printable.content} />
                    </div>
                    <div className="printable-artifact-footer">
                      <span>Buzzcaf Media Studio — Generated Artifact</span>
                      <span>{printable.projectName}</span>
                    </div>
                  </td>
                </tr>
              </tbody>
              <tfoot>
                <tr>
                  <td className="buzzcaf-print-bottom-spacer">
                    <div style={{ height: '0.5in', minHeight: '0.5in', maxHeight: '0.5in', lineHeight: '0.5in', fontSize: 1 }}>&nbsp;</div>
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>,
          document.body,
        )}
    </div>
  );
}
