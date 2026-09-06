import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  AlertCircle,
  Bot,
  ChevronUp,
  Compass,
  Database,
  FolderGit2,
  HeartPulse,
  LayoutDashboard,
  MessageSquare,
  Settings as SettingsIcon,
  Users,
} from 'lucide-react';

import { StudioProvider, useStudio } from './state/studio';
import type { TabId } from './lib/types';
import StudioChat from './pages/StudioChat';
import Dashboard from './pages/Dashboard';
import Projects from './pages/Projects';
import TopicVault from './pages/TopicVault';
import Workforce from './pages/Workforce';
import Health from './pages/Health';
import Settings from './pages/Settings';
import AgentCreatorStudio from './pages/ai/AgentCreatorStudio';
import AgentsGroupChat from './pages/ai/AgentsGroupChat';

// The shell: sidebar, header, and the active page. Every page reads shared
// state from StudioProvider; nothing here fetches. The Studio Assistant is the
// landing tab (roadmap v5, 2.5) - before v5 chat was two clicks away inside
// the Topic Vault, and four tabs showed static mock data.

interface NavItem {
  id: TabId;
  label: string;
  icon: ReactNode;
  title: string;
}

interface NavSection {
  title: string;
  items: NavItem[];
}

const SECTIONS: NavSection[] = [
  {
    title: 'Studio',
    items: [
      { id: 'studio_chat', label: 'Studio Assistant', icon: <MessageSquare size={18} style={{ color: '#a78bfa' }} />, title: 'Studio Assistant' },
      { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard size={18} />, title: 'Studio overview' },
      { id: 'projects', label: 'Projects', icon: <FolderGit2 size={18} />, title: 'Production projects' },
      { id: 'topic_vault', label: 'Topic Vault', icon: <Compass size={18} />, title: 'Topic ideas and saved vault' },
    ],
  },
  {
    title: 'Agents',
    items: [
      { id: 'agent_creator_studio', label: 'Agents Workbench', icon: <Bot size={18} style={{ color: '#a78bfa' }} />, title: 'Agents Workbench' },
      { id: 'agents_group_chat', label: 'Group Chat', icon: <Users size={18} style={{ color: '#a78bfa' }} />, title: 'Agents group chat' },
      { id: 'ai_workforce', label: 'Personas', icon: <Users size={18} />, title: 'Agent personas' },
    ],
  },
  {
    title: 'System',
    items: [
      { id: 'health', label: 'Health', icon: <HeartPulse size={18} />, title: 'System diagnostics' },
      { id: 'settings', label: 'Settings', icon: <SettingsIcon size={18} />, title: 'AI provider settings' },
    ],
  },
];

const TITLES: Record<TabId, string> = Object.fromEntries(
  SECTIONS.flatMap((s) => s.items.map((i) => [i.id, i.title])),
) as Record<TabId, string>;

function Shell() {
  const { tab, navigate, health, healthInfo, groupChatAgentIds, setGroupChatAgentIds, toast } = useStudio();
  const workspaceRef = useRef<HTMLDivElement | null>(null);
  const [showTop, setShowTop] = useState(false);

  useEffect(() => {
    workspaceRef.current?.scrollTo({ top: 0 });
  }, [tab]);

  const go = (id: TabId) => {
    if (id === 'agents_group_chat' && groupChatAgentIds.length === 0) {
      toast('Pick agents in the Agents Workbench first, then launch the group chat.', 'info');
      navigate('agent_creator_studio');
      return;
    }
    navigate(id);
  };

  return (
    <div className="app-container">
      <div className="sidebar">
        <div className="sidebar-brand">
          <Database size={24} />
          <span>Buzzcaf Studio</span>
        </div>

        {SECTIONS.map((section) => (
          <div key={section.title}>
            <div className="sidebar-section-title">{section.title}</div>
            <div className="sidebar-menu">
              {section.items.map((item) => (
                <div
                  key={item.id}
                  className={`menu-item ${tab === item.id ? 'active' : ''}`}
                  onClick={() => go(item.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => e.key === 'Enter' && go(item.id)}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </div>
              ))}
            </div>
          </div>
        ))}

        <div className="sidebar-footer">
          <p>Buzzcaf Studio v5</p>
          <p>Controlled by Dexter</p>
        </div>
      </div>

      <div
        className="workspace"
        ref={workspaceRef}
        onScroll={() => setShowTop((workspaceRef.current?.scrollTop || 0) > 400)}
      >
        <div className="header">
          <div className="header-title">{TITLES[tab]}</div>
          <div className="header-status">
            <div className="status-badge" title={healthInfo?.version ? `Studio backend v${healthInfo.version}` : undefined}>
              <div className="status-dot" style={{ backgroundColor: health === 'online' ? '#4ade80' : health === 'offline' ? '#ef4444' : '#94a3b8' }} />
              <span>{health === 'online' ? 'Backend online' : health === 'offline' ? 'Backend offline' : 'Checking backend…'}</span>
            </div>
          </div>
        </div>

        <div className="main-content">
          {health === 'offline' && (
            <div style={{ backgroundColor: '#2d141b', border: '1px solid #7f1d1d', borderRadius: 8, padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 10, color: '#fca5a5', marginBottom: 24 }}>
              <AlertCircle size={20} />
              <span>The Studio backend is not answering on this port. Nothing below is live until it is back.</span>
            </div>
          )}

          {tab === 'studio_chat' && <StudioChat />}
          {tab === 'dashboard' && <Dashboard />}
          {tab === 'projects' && <Projects />}
          {tab === 'topic_vault' && <TopicVault />}
          {tab === 'agent_creator_studio' && (
            <AgentCreatorStudio
              onLaunchGroupChat={(ids) => {
                setGroupChatAgentIds(ids);
                navigate('agents_group_chat');
              }}
            />
          )}
          {tab === 'agents_group_chat' && (
            <AgentsGroupChat selectedAgentIds={groupChatAgentIds} onBackToStudio={() => navigate('agent_creator_studio')} />
          )}
          {tab === 'ai_workforce' && <Workforce />}
          {tab === 'health' && <Health />}
          {tab === 'settings' && <Settings />}
        </div>
      </div>

      {showTop && (
        <button
          type="button"
          onClick={() => workspaceRef.current?.scrollTo({ top: 0, behavior: 'smooth' })}
          style={{ position: 'fixed', bottom: 32, right: 32, zIndex: 999, width: 46, height: 46, borderRadius: '50%', backgroundColor: '#f43f5e', color: '#ffffff', border: 'none', boxShadow: '0 8px 20px rgba(244, 63, 94, 0.5)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          title="Scroll to top"
        >
          <ChevronUp size={24} />
        </button>
      )}
    </div>
  );
}

export default function App() {
  return (
    <StudioProvider>
      <Shell />
    </StudioProvider>
  );
}
