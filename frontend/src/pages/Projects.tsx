import { useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, ChevronRight, Circle, Clock, FileText, Play, RotateCw, X } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError, ApiError } from '../services/api';
import Markdown from '../components/Markdown';
import type { Project, StepRecord, WorkflowStepInfo } from '../lib/types';

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
  done: '#4ade80',
  current: '#f59e0b',
  failed: '#ef4444',
  waiting: '#a78bfa',
  pending: '#475569',
};

export default function Projects() {
  const { projects, workflows, refreshProjects, toast, health } = useStudio();
  const [runningId, setRunningId] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [feedback, setFeedback] = useState<Record<string, string>>({});
  const [openId, setOpenId] = useState<string | null>(null);
  const [assetName, setAssetName] = useState<string | null>(null);
  const [assetBody, setAssetBody] = useState<string>('');
  const [assetBusy, setAssetBusy] = useState(false);
  const poll = useRef<number | null>(null);

  useEffect(() => () => { if (poll.current) window.clearInterval(poll.current); }, []);

  const open = useMemo(() => projects.find((p) => p.id === openId) || null, [projects, openId]);
  const openWorkflow = useMemo(
    () => (open ? workflows.find((w) => (w.id || w.name) === open.workflow_name) || null : null),
    [open, workflows],
  );

  const select = (project: Project) => {
    setOpenId(project.id);
    setAssetName(null);
    setAssetBody('');
  };

  const showAsset = async (project: Project, name: string) => {
    setAssetName(name);
    setAssetBusy(true);
    setAssetBody('');
    try {
      const data = await getJson<Record<string, unknown>>(
        `/api/projects/${encodeURIComponent(project.id)}/asset/${encodeURIComponent(name)}`,
      );
      // Text assets come back as {content}; a .json asset comes back parsed.
      const content = typeof data?.content === 'string' ? data.content : `\`\`\`json\n${JSON.stringify(data, null, 2)}\n\`\`\``;
      setAssetBody(content);
    } catch (err) {
      setAssetBody('');
      toast(describeError(err), 'error');
    } finally {
      setAssetBusy(false);
    }
  };

  const run = async (project: Project, mode: 'execute' | 'approve', notes?: string) => {
    if (runningId) return;
    setRunningId(project.id);
    setLog([mode === 'approve' ? 'Approving the step that is waiting…' : 'Starting the next workflow step…']);
    poll.current = window.setInterval(async () => {
      try {
        const lines = await getJson<string[]>(`/api/projects/${encodeURIComponent(project.id)}/logs`);
        if (Array.isArray(lines) && lines.length) setLog(lines);
      } catch {
        // keep the last log we had
      }
    }, 700);
    try {
      const updated = await postJson<Project>(
        `/api/projects/${encodeURIComponent(project.id)}/${mode}`,
        notes ? { feedback: notes } : {},
        { signal: AbortSignal.timeout(300_000) },
      );
      const step = lastStep(updated);
      if (step?.status === 'paused_for_approval') toast(`${step.step_name || 'The step'} is waiting for your approval.`, 'info');
      else if (updated.status === 'completed') toast(`${project.name} is complete.`, 'success');
      else toast(`Ran ${step?.step_name || 'the next step'}.`, 'success');
      setFeedback((prev) => ({ ...prev, [project.id]: '' }));
    } catch (err) {
      // 409 means the project moved on between the render and the click; the
      // list is refreshed below either way, so say so rather than just failing.
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

  return (
    <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
          <h2 style={{ margin: 0, fontSize: '1.5rem', color: '#ffffff' }}>Projects</h2>
          <button type="button" className="btn btn-outline" onClick={() => refreshProjects()}>
            <RotateCw size={16} />
            <span>Refresh</span>
          </button>
        </div>

        {projects.length === 0 && (
          <div className="panel-card" style={{ textAlign: 'center', color: '#94a3b8', padding: 40 }}>
            <p style={{ margin: 0, fontSize: '1rem' }}>{health === 'offline' ? 'The Studio backend is offline.' : 'No projects yet.'}</p>
            <p style={{ fontSize: '0.85rem', marginTop: 6 }}>Create one from the Dashboard, send a topic from the Vault, or ask Dexter to start one.</p>
          </div>
        )}

        <div className="project-list">
          {projects.map((proj) => {
            const step = lastStep(proj);
            const waiting = step?.status === 'paused_for_approval';
            const busy = runningId === proj.id;
            return (
              <div key={proj.id} className="project-item" style={openId === proj.id ? { borderColor: '#a78bfa' } : undefined}>
                <div
                  className="project-info"
                  onClick={() => select(proj)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === 'Enter' && select(proj)}
                  style={{ cursor: 'pointer' }}
                >
                  <div className="project-name">{proj.name}</div>
                  <div className="project-meta">
                    <span>ID: <code style={{ color: '#94a3b8' }}>{proj.id}</code></span>
                    <span>Channel: <span className="brand-badge">{proj.brand}</span></span>
                    <span>Workflow: <code style={{ color: '#e2e8f0' }}>{proj.workflow_name}</code></span>
                    {proj.current_step && <span>Step: <strong style={{ color: '#e2e8f0' }}>{proj.current_step}</strong></span>}
                    <span style={{ color: '#a78bfa', display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                      Open <ChevronRight size={13} />
                    </span>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                  <span className={`status-badge-inline status-${proj.status}`}>
                    {waiting ? 'AWAITING APPROVAL' : String(proj.status || 'unknown').toUpperCase()}
                  </span>
                  {waiting ? (
                    <button type="button" className="btn" disabled={!!runningId} onClick={() => run(proj, 'approve')} style={{ padding: '8px 16px', fontSize: '0.85rem' }}>
                      <CheckCircle2 size={14} />
                      <span>Approve & continue</span>
                    </button>
                  ) : (
                    proj.status !== 'completed' && (
                      <button type="button" className="btn" disabled={!!runningId} onClick={() => run(proj, 'execute')} style={{ padding: '8px 16px', fontSize: '0.85rem' }}>
                        <Play size={14} />
                        <span>{busy ? 'Running…' : 'Run next step'}</span>
                      </button>
                    )
                  )}
                </div>

                {waiting && (
                  <div style={{ width: '100%', display: 'flex', gap: 10, alignItems: 'center', marginTop: 8 }}>
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

                {busy && (
                  <div style={{ width: '100%' }}>
                    <div className="logs-panel">
                      {log.map((line, i) => <div key={i}>{line}</div>)}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {open && (
        <div className="panel-card" style={{ width: 460, flexShrink: 0, position: 'sticky', top: 0, maxHeight: 'calc(100vh - 160px)', overflowY: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
            <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0 }}>{open.name}</h3>
            <button type="button" onClick={() => setOpenId(null)} aria-label="Close panel" style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', display: 'flex' }}>
              <X size={16} />
            </button>
          </div>

          <div style={{ marginTop: 16 }}>
            <div style={{ fontSize: '0.8rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>Steps</div>
            {openWorkflow?.steps?.length ? (
              <div className="timeline-container" style={{ marginTop: 0 }}>
                {openWorkflow.steps.map((s, i) => {
                  const state = stepState(open, s);
                  return (
                    <div key={s.name} className="timeline-step" style={{ padding: '10px 14px', gap: 12, borderColor: state === 'pending' ? '#1e2230' : STATE_COLOR[state] }}>
                      <div className="step-num" style={{ color: STATE_COLOR[state] }}>{i + 1}</div>
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div style={{ color: '#ffffff', fontSize: '0.88rem', fontWeight: 600 }}>{s.name}</div>
                        <div style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
                          {s.agent_role}
                          {s.requires_approval && <span style={{ color: '#a78bfa' }}> · needs approval</span>}
                        </div>
                      </div>
                      <span style={{ fontSize: '0.72rem', color: STATE_COLOR[state], textTransform: 'uppercase', fontWeight: 700 }}>{state}</span>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p style={{ color: '#94a3b8', fontSize: '0.85rem', margin: 0 }}>
                No definition loaded for <code>{open.workflow_name}</code>.
              </p>
            )}
          </div>

          <div style={{ marginTop: 24 }}>
            <div style={{ fontSize: '0.8rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>Assets</div>
            {Object.keys(open.assets || {}).length === 0 ? (
              <p style={{ color: '#94a3b8', fontSize: '0.85rem', margin: 0 }}>Nothing produced yet.</p>
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {Object.entries(open.assets || {}).map(([name, file]) => (
                  <button
                    key={name}
                    type="button"
                    onClick={() => showAsset(open, name)}
                    title={file}
                    style={{
                      backgroundColor: assetName === name ? '#1c1827' : '#161923',
                      border: `1px solid ${assetName === name ? '#a78bfa' : '#232738'}`,
                      color: '#e2e8f0', padding: '6px 12px', borderRadius: 8, fontSize: '0.8rem',
                      cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6,
                    }}
                  >
                    <FileText size={13} />
                    {name}
                  </button>
                ))}
              </div>
            )}
          </div>

          {assetName && (
            <div style={{ marginTop: 16, borderTop: '1px solid #1e2230', paddingTop: 16 }}>
              <div style={{ fontSize: '0.8rem', color: '#94a3b8', marginBottom: 10 }}>
                {open.assets?.[assetName] || assetName}
              </div>
              {assetBusy ? (
                <div style={{ color: '#94a3b8', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Clock size={14} className="spin" /> Loading…
                </div>
              ) : assetBody ? (
                <Markdown text={assetBody} />
              ) : (
                <div style={{ color: '#94a3b8', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Circle size={12} /> Nothing to show.
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
