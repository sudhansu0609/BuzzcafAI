import { useEffect, useState, type FormEvent } from 'react';
import { Activity, CheckCircle2, FolderGit2, PlusCircle, TrendingUp } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';
import { CHANNEL_META, workflowFor } from '../lib/channels';
import type { AgentInfo } from '../lib/types';

const PROVIDER_LABEL: Record<string, string> = {
  gemini: 'Google Gemini',
  openai: 'OpenAI',
  lm_studio: 'Local LM Studio',
};

export default function Dashboard() {
  const { projects, settings, health, healthInfo, brands, workflows, refreshProjects, navigate, toast } = useStudio();
  const [agentCount, setAgentCount] = useState<number | null>(null);
  const [name, setName] = useState('');
  const [brand, setBrand] = useState('Beyond3Baje');
  const [workflow, setWorkflow] = useState(workflowFor('Beyond3Baje'));
  const [creating, setCreating] = useState(false);
  const [allowAll, setAllowAll] = useState(false);
  const [durationMin, setDurationMin] = useState(8);

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

  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim() || creating) return;
    setCreating(true);
    try {
      await postJson('/api/projects', { name: name.trim(), brand, workflow_name: workflow, allow_all: allowAll, target_duration_minutes: durationMin });
      toast(`Project "${name.trim()}" created.`, 'success');
      setName('');
      await refreshProjects();
      navigate('projects');
    } catch (err) {
      toast(`Could not create the project: ${describeError(err)}`, 'error');
    } finally {
      setCreating(false);
    }
  };

  const inProgress = projects.filter((p) => p.status !== 'completed').length;
  const provider = settings?.selected_provider ? PROVIDER_LABEL[settings.selected_provider] || settings.selected_provider : '—';

  return (
    <div>
      <div className="metrics-grid">
        <div className="metric-card">
          <div className="metric-icon-bg"><FolderGit2 /></div>
          <span className="metric-label">Projects</span>
          <span className="metric-val">{projects.length}</span>
          <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>{inProgress} in progress</span>
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

      <div className="panel-card">
        <h3 className="panel-title"><PlusCircle size={20} /> New production project</h3>
        <form onSubmit={create}>
          <div className="form-row">
            <div className="form-group">
              <label>Title</label>
              <input type="text" className="form-control" placeholder="e.g. The vanishing guard of Bhangarh Fort" value={name} onChange={(e) => setName(e.target.value)} required />
            </div>
            <div className="form-group">
              <label>Channel</label>
              <select className="form-control" value={brand} onChange={(e) => pickBrand(e.target.value)}>
                {brandOptions.map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
            </div>
            <div className="form-group">
              <label>Workflow</label>
              {workflowOptions.length > 0 ? (
                <select className="form-control" value={workflow} onChange={(e) => setWorkflow(e.target.value)}>
                  {workflowOptions.map((w) => <option key={w} value={w}>{w}</option>)}
                </select>
              ) : (
                <input type="text" className="form-control" value={workflow} onChange={(e) => setWorkflow(e.target.value)} />
              )}
            </div>
            <div className="form-group">
              <label>Target length (min)</label>
              <input
                type="number"
                className="form-control"
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
                checked={allowAll}
                onChange={(e) => setAllowAll(e.target.checked)}
                style={{ width: 16, height: 16, accentColor: '#10b981', cursor: 'pointer' }}
              />
              <span>Allow all steps (run continuously without waiting for manual approval)</span>
            </label>
          </div>
          <button type="submit" className="btn" disabled={creating || health === 'offline'}>
            <PlusCircle size={18} />
            <span>{creating ? 'Creating…' : 'Create project'}</span>
          </button>
          {health === 'offline' && <span style={{ marginLeft: 12, color: '#fca5a5', fontSize: '0.85rem' }}>Backend offline.</span>}
        </form>
      </div>
    </div>
  );
}
