import { useEffect, useRef, useState } from 'react';
import { CheckCircle2, Play, RotateCw } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';
import type { Project, StepRecord } from '../lib/types';

function lastStep(p: Project): StepRecord | null {
  const history = (p.history || p.steps_history || []) as StepRecord[];
  return history.length ? history[history.length - 1] : null;
}

export default function Projects() {
  const { projects, refreshProjects, toast, health } = useStudio();
  const [runningId, setRunningId] = useState<string | null>(null);
  const [log, setLog] = useState<string[]>([]);
  const [feedback, setFeedback] = useState<Record<string, string>>({});
  const poll = useRef<number | null>(null);

  useEffect(() => () => { if (poll.current) window.clearInterval(poll.current); }, []);

  const execute = async (project: Project, notes?: string) => {
    if (runningId) return;
    setRunningId(project.id);
    setLog(['Starting the next workflow step…']);
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
        `/api/projects/${encodeURIComponent(project.id)}/execute`,
        notes ? { feedback: notes } : {},
        { signal: AbortSignal.timeout(300_000) },
      );
      const step = lastStep(updated);
      if (step?.status === 'paused_for_approval') toast(`${step.step_name || 'The step'} is waiting for your approval.`, 'info');
      else if (updated.status === 'completed') toast(`${project.name} is complete.`, 'success');
      else toast(`Ran ${step?.step_name || 'the next step'}.`, 'success');
      setFeedback((prev) => ({ ...prev, [project.id]: '' }));
    } catch (err) {
      const detail = describeError(err);
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
    <div>
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
            <div key={proj.id} className="project-item">
              <div className="project-info">
                <div className="project-name">{proj.name}</div>
                <div className="project-meta">
                  <span>ID: <code style={{ color: '#94a3b8' }}>{proj.id}</code></span>
                  <span>Channel: <span className="brand-badge">{proj.brand}</span></span>
                  <span>Workflow: <code style={{ color: '#e2e8f0' }}>{proj.workflow_name}</code></span>
                  {proj.current_step && <span>Step: <strong style={{ color: '#e2e8f0' }}>{proj.current_step}</strong></span>}
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                <span className={`status-badge-inline status-${proj.status}`}>
                  {waiting ? 'AWAITING APPROVAL' : String(proj.status || 'unknown').toUpperCase()}
                </span>
                {waiting ? (
                  <button type="button" className="btn" disabled={!!runningId} onClick={() => execute(proj)} style={{ padding: '8px 16px', fontSize: '0.85rem' }}>
                    <CheckCircle2 size={14} />
                    <span>Approve & continue</span>
                  </button>
                ) : (
                  proj.status !== 'completed' && (
                    <button type="button" className="btn" disabled={!!runningId} onClick={() => execute(proj)} style={{ padding: '8px 16px', fontSize: '0.85rem' }}>
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
                    onClick={() => execute(proj, feedback[proj.id])}
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
  );
}
