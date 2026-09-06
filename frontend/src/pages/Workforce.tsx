import { useEffect, useState } from 'react';
import { Cpu, Search, Users } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, describeError } from '../services/api';
import type { AgentInfo } from '../lib/types';

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

  const visible = agents.filter((a) => !filter || a.name.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div>
      <div className="panel-card" style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
        <div>
          <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0 }}><Users size={20} /> Agent personas ({agents.length})</h3>
          <p style={{ color: '#94a3b8', margin: '4px 0 0 0' }}>Every persona defined under backend/prompts/agents. Workflows pick from these by role.</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Search size={16} style={{ color: '#94a3b8' }} />
          <input type="text" className="form-control" placeholder="Filter by name…" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ padding: '6px 12px', fontSize: '0.85rem', width: 220 }} />
        </div>
      </div>
      {agents.length === 0 ? (
        <div className="panel-card" style={{ textAlign: 'center', padding: 40, color: '#94a3b8' }}>
          {health === 'offline' ? 'The Studio backend is offline.' : 'No personas were returned by the backend.'}
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16 }}>
          {visible.map((ag) => (
            <div key={ag.name} className="panel-card" style={{ padding: '14px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', margin: 0 }}>
              <div>
                <h4 style={{ margin: '0 0 4px 0', color: '#ffffff', fontSize: '0.95rem' }}>{ag.name}</h4>
                <span style={{ fontSize: '0.78rem', color: '#94a3b8' }}>{ag.file || 'registered'}</span>
              </div>
              <Cpu size={20} style={{ color: '#a78bfa', opacity: 0.8 }} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
