import { useEffect, useState } from 'react';
import { Building2, Send } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';
import Markdown from '../components/Markdown';

// The 13 departments as something you can talk to (roadmap v9, E2). The task
// goes to the manager unless you pick a specialist.

interface DepartmentInfo {
  name: string;
  manager: string;
  specialists: string[];
}

interface DepartmentReply {
  department: string;
  agent: string;
  simulated?: boolean;
  output: string;
}

export default function Departments() {
  const { toast, health } = useStudio();
  const [departments, setDepartments] = useState<DepartmentInfo[]>([]);
  const [task, setTask] = useState<Record<string, string>>({});
  const [role, setRole] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [reply, setReply] = useState<Record<string, DepartmentReply>>({});

  useEffect(() => {
    getJson<{ departments?: DepartmentInfo[] }>('/api/departments')
      .then((d) => setDepartments(d.departments || []))
      .catch((err) => {
        setDepartments([]);
        if (health !== 'offline') toast(describeError(err), 'error');
      });
  }, [health, toast]);

  const ask = async (dept: DepartmentInfo) => {
    const text = (task[dept.name] || '').trim();
    if (!text || busy) return;
    setBusy(dept.name);
    try {
      const data = await postJson<DepartmentReply>(
        `/api/departments/${encodeURIComponent(dept.name)}/execute`,
        { task: text, role: role[dept.name] || undefined },
        { signal: AbortSignal.timeout(180_000) },
      );
      setReply((prev) => ({ ...prev, [dept.name]: data }));
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <div className="panel-card" style={{ marginBottom: 24 }}>
        <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0 }}>
          <Building2 size={20} /> Departments ({departments.length})
        </h3>
        <p style={{ color: '#94a3b8', margin: '4px 0 0 0' }}>
          Every persona reports into one of these. Ask a department and its manager answers, or pick a specialist.
        </p>
      </div>

      {departments.length === 0 ? (
        <div className="panel-card" style={{ textAlign: 'center', padding: 40, color: '#94a3b8' }}>
          {health === 'offline' ? 'The Studio backend is offline.' : 'No departments were returned by the backend.'}
        </div>
      ) : (
        departments.map((dept) => {
          const answer = reply[dept.name];
          return (
            <div key={dept.name} className="panel-card">
              <h3 className="panel-title">
                <Building2 size={18} /> {dept.name}
                <span style={{ color: '#94a3b8', fontWeight: 400, fontSize: '0.85rem' }}>
                  &nbsp;· {dept.manager} + {dept.specialists.length} specialists
                </span>
              </h3>

              {dept.specialists.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14 }}>
                  {dept.specialists.map((s) => (
                    <span key={s} style={{ backgroundColor: 'var(--bg-pill)', border: '1px solid var(--border-card)', borderRadius: 6, padding: '3px 9px', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                      {s}
                    </span>
                  ))}
                </div>
              )}

              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
                <input
                  type="text"
                  className="form-control"
                  style={{ flex: 1, minWidth: 260 }}
                  placeholder={`Ask ${dept.name}…`}
                  value={task[dept.name] || ''}
                  onChange={(e) => setTask((prev) => ({ ...prev, [dept.name]: e.target.value }))}
                  onKeyDown={(e) => e.key === 'Enter' && ask(dept)}
                />
                <select
                  className="form-control"
                  style={{ width: 'auto' }}
                  value={role[dept.name] || ''}
                  onChange={(e) => setRole((prev) => ({ ...prev, [dept.name]: e.target.value }))}
                >
                  <option value="">{dept.manager} (manager)</option>
                  {dept.specialists.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
                <button
                  type="button"
                  className="btn"
                  disabled={busy !== null || !(task[dept.name] || '').trim()}
                  onClick={() => ask(dept)}
                >
                  <Send size={16} />
                  <span>{busy === dept.name ? 'Working…' : 'Ask'}</span>
                </button>
              </div>

              {answer && (
                <div style={{ marginTop: 16, borderTop: '1px solid #1e2230', paddingTop: 14 }}>
                  <div style={{ fontSize: '0.8rem', color: '#94a3b8', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 10 }}>
                    <strong style={{ color: '#e2e8f0' }}>{answer.agent}</strong>
                    {answer.simulated && (
                      <span style={{ color: '#f59e0b', fontWeight: 700, fontSize: '0.72rem' }}>
                        ⚠ SIMULATED — no AI provider responded.
                      </span>
                    )}
                  </div>
                  <Markdown text={answer.output} />
                </div>
              )}
            </div>
          );
        })
      )}
    </div>
  );
}
