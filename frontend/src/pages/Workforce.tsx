import { useEffect, useMemo, useState } from 'react';
import { Cpu, Search, Users } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, describeError } from '../services/api';
import type { AgentInfo } from '../lib/types';

// Every registered persona, grouped by the department in its frontmatter
// (roadmap v9, A2). Before v9 this listed filenames and a made-up status.

export default function Workforce() {
  const { toast, health } = useStudio();
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [filter, setFilter] = useState('');

  useEffect(() => {
    getJson<{ agents?: AgentInfo[] }>('/api/agents')
      .then((d) => setAgents(d.agents || []))
      .catch((err) => {
        setAgents([]);
        if (health !== 'offline') toast(describeError(err), 'error');
      });
  }, [health, toast]);

  const groups = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    const byDept = new Map<string, AgentInfo[]>();
    for (const ag of agents) {
      const dept = ag.department || 'General';
      if (needle && !ag.name.toLowerCase().includes(needle) && !dept.toLowerCase().includes(needle)) continue;
      const list = byDept.get(dept) || [];
      list.push(ag);
      byDept.set(dept, list);
    }
    return [...byDept.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [agents, filter]);

  const shown = groups.reduce((n, [, list]) => n + list.length, 0);

  return (
    <div>
      <div className="panel-card" style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
        <div>
          <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0 }}>
            <Users size={20} /> Agent personas ({agents.length}) · {groups.length} departments
          </h3>
          <p style={{ color: '#94a3b8', margin: '4px 0 0 0' }}>
            Every persona registered from backend/prompts/agents. Workflows, chat and departments all pick from these.
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Search size={16} style={{ color: '#94a3b8' }} />
          <input type="text" className="form-control" placeholder="Filter by name or department…" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ padding: '6px 12px', fontSize: '0.85rem', width: 240 }} />
        </div>
      </div>

      {shown === 0 ? (
        <div className="panel-card" style={{ textAlign: 'center', padding: 40, color: '#94a3b8' }}>
          {agents.length === 0
            ? (health === 'offline' ? 'The Studio backend is offline.' : 'No personas were returned by the backend.')
            : `No persona matches “${filter}”.`}
        </div>
      ) : (
        groups.map(([dept, list]) => (
          <div key={dept} className="panel-card">
            <h3 className="panel-title">
              <Users size={18} /> {dept} <span style={{ color: '#94a3b8', fontWeight: 400 }}>({list.length})</span>
            </h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
              {list.map((ag) => (
                <div key={ag.name} style={{ backgroundColor: '#12141d', border: '1px solid #1e2230', borderRadius: 8, padding: '12px 16px', display: 'flex', gap: 12 }}>
                  <Cpu size={18} style={{ color: '#a78bfa', opacity: 0.8, flexShrink: 0, marginTop: 2 }} />
                  <div style={{ minWidth: 0 }}>
                    <h4 style={{ margin: '0 0 4px 0', color: '#ffffff', fontSize: '0.95rem' }}>{ag.name}</h4>
                    <p style={{ margin: 0, fontSize: '0.78rem', color: '#94a3b8', lineHeight: 1.5 }}>
                      {ag.role || 'No role stated in this persona file.'}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
}
