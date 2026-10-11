import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  BarChart3,
  AlertCircle,
  Bot,
  Building2,
  CalendarClock,
  ChevronUp,
  Compass,
  FolderGit2,
  HeartPulse,
  LayoutDashboard,
  LayoutGrid,
  Menu,
  Music as MusicIcon,
  MessageSquare,
  Newspaper,
  PenLine,
  PenTool,
  PanelLeftClose,
  PanelLeftOpen,
  Settings as SettingsIcon,
  Users,
  X,
} from 'lucide-react';

import { StudioProvider, useStudio } from './state/studio';
import { ThemeProvider } from './state/ThemeContext';
import { ThemeSwitcher } from './components/ThemeSwitcher';
import { ChannelPicker } from './components/ChannelPicker';
import type { TabId } from './lib/types';
import StudioChat from './pages/StudioChat';
import Dashboard from './pages/Dashboard';
import Projects from './pages/Projects';
import TopicVault from './pages/TopicVault';
import Music from './pages/Music';
import WritingStyle from './pages/WritingStyle';
import SchedulerDesk from './pages/SchedulerDesk';
import BulkEdit from './pages/BulkEdit';
import Board from './pages/Board';
import Analyze from './pages/Analyze';
import Research from './pages/Research';
import Workforce from './pages/Workforce';
import Departments from './pages/Departments';
import Health from './pages/Health';
import Settings from './pages/Settings';
import Logs from './pages/Logs';
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
      { id: 'scheduler_desk', label: 'Scheduler Desk', icon: <CalendarClock size={18} style={{ color: '#f59e0b' }} />, title: 'Scheduler Desk: shorts and long-form schedulers' },
      { id: 'bulk_edit', label: 'Bulk Editor', icon: <PenLine size={18} style={{ color: '#38bdf8' }} />, title: 'Bulk Editor' },
      { id: 'topic_vault', label: 'Topic Vault', icon: <Compass size={18} />, title: 'Topic ideas and saved vault' },
      { id: 'board', label: 'Board', icon: <LayoutGrid size={18} />, title: 'Topic board' },
      { id: 'analyze', label: 'Analyze', icon: <BarChart3 size={18} />, title: 'Why a video or channel performs, and how to model ours on it' },
      { id: 'research', label: 'Research', icon: <Newspaper size={18} />, title: 'Search public archives, books and newspapers' },
      { id: 'music', label: 'Music', icon: <MusicIcon size={18} />, title: 'Generated background music and the licensed library' },
      { id: 'writing_style', label: 'Writing Style', icon: <PenTool size={18} style={{ color: '#34d399' }} />, title: 'Your own writing style, per channel: what every writing agent matches' },
    ],
  },
  {
    title: 'Agents',
    items: [
      { id: 'agent_creator_studio', label: 'Agents Workbench', icon: <Bot size={18} style={{ color: '#a78bfa' }} />, title: 'Agents Workbench' },
      { id: 'agents_group_chat', label: 'Group Chat', icon: <Users size={18} style={{ color: '#a78bfa' }} />, title: 'Agents group chat' },
      { id: 'ai_workforce', label: 'Personas', icon: <Users size={18} />, title: 'Agent personas' },
      { id: 'departments', label: 'Departments', icon: <Building2 size={18} />, title: 'Departments' },
    ],
  },
  {
    title: 'System',
    items: [
      { id: 'logs', label: 'Error Logs', icon: <AlertCircle size={18} style={{ color: '#f87171' }} />, title: 'System & error logs' },
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
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  // The Bulk Editor is a framed app: once opened it stays mounted (hidden) so
  // switching tabs neither reloads it nor drops the progress of a running job.
  const [bulkEditOpened, setBulkEditOpened] = useState(tab === 'bulk_edit');
  useEffect(() => {
    if (tab === 'bulk_edit') setBulkEditOpened(true);
  }, [tab]);
  // Desktop only: shrink the sidebar to an icon rail. Remembered per browser.
  const [collapsed, setCollapsed] = useState(() => {
    try { return localStorage.getItem('buzzcaf.sidebarCollapsed') === '1'; } catch { return false; }
  });
  const toggleCollapsed = () => setCollapsed((c) => {
    try { localStorage.setItem('buzzcaf.sidebarCollapsed', c ? '0' : '1'); } catch { /* ignore */ }
    return !c;
  });

  useEffect(() => {
    workspaceRef.current?.scrollTo({ top: 0 });
  }, [tab]);

  const go = (id: TabId) => {
    setMobileMenuOpen(false);
    if (id === 'agents_group_chat' && groupChatAgentIds.length === 0) {
      toast('Pick agents in the Agents Workbench first, then launch the group chat.', 'info');
      navigate('agent_creator_studio');
      return;
    }
    navigate(id);
  };

  return (
    <div className="app-container">
      {/* Mobile Backdrop */}
      {mobileMenuOpen && (
        <div
          className="sidebar-backdrop"
          onClick={() => setMobileMenuOpen(false)}
          role="presentation"
        />
      )}

      {/* Sidebar Navigation */}
      <div className={`sidebar ${mobileMenuOpen ? 'open' : ''} ${collapsed ? 'collapsed' : ''}`}>
        <div className="sidebar-brand">
          {/* Full logo; the collapsed rail shows the B mark. Each has a light-theme
              (dark ink) and a dark-theme (light ink) file, picked by CSS. */}
          <div className="sidebar-brand-content" aria-label="Buzzcaf AI Studio">
            <img className="brand-logo brand-logo-full brand-on-light" src={`${import.meta.env.BASE_URL}logo.png`} alt="Buzzcaf AI Studio" />
            <img className="brand-logo brand-logo-full brand-on-dark" src={`${import.meta.env.BASE_URL}logo-dark.png`} alt="" />
            <img className="brand-logo brand-logo-mark brand-on-light" src={`${import.meta.env.BASE_URL}logo-mark.png`} alt="" />
            <img className="brand-logo brand-logo-mark brand-on-dark" src={`${import.meta.env.BASE_URL}logo-mark-dark.png`} alt="" />
          </div>
          <button
            type="button"
            className="sidebar-collapse-btn"
            onClick={toggleCollapsed}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
          </button>
          <button
            type="button"
            className="sidebar-close-btn"
            onClick={() => setMobileMenuOpen(false)}
            aria-label="Close menu"
          >
            <X size={20} />
          </button>
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
                  title={collapsed ? item.label : undefined}
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
          <div className="header-left">
            <button
              type="button"
              className="mobile-menu-toggle"
              onClick={() => setMobileMenuOpen((v) => !v)}
              aria-label={mobileMenuOpen ? 'Close navigation menu' : 'Open navigation menu'}
              aria-expanded={mobileMenuOpen}
            >
              {mobileMenuOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
            <div className="header-title" title={TITLES[tab]}>{TITLES[tab]}</div>
          </div>

          <div className="header-status">
            <ChannelPicker />
            <ThemeSwitcher />
            {(() => {
              const ms = healthInfo?.model_status;
              const isBackendUp = health === 'online';
              const isModelConnected = Boolean(ms?.connected && ms?.loaded);
              const isModelLoading = Boolean(ms?.connected && !ms?.loaded);

              let dotColor = '#94a3b8';
              let badgeText = 'Checking backend…';
              let titleText = 'Checking backend & AI model status';

              if (!isBackendUp) {
                dotColor = '#ef4444';
                badgeText = 'Backend offline';
                titleText = 'Studio backend is not reachable on this port.';
              } else if (isModelConnected) {
                dotColor = '#4ade80';
                const modelLabel = ms?.active_model || ms?.configured_model || ms?.provider || 'AI';
                badgeText = `Online • ${modelLabel}`;
                titleText = `Backend Online & Connected to ${ms?.provider} (${modelLabel})`;
              } else if (isModelLoading) {
                dotColor = '#f59e0b';
                badgeText = 'AI ready (loads on use)';
                titleText = `Backend online. ${ms?.provider}: ${ms?.configured_model} is not on the GPU; it loads on the first request and unloads when idle.`;
              } else {
                dotColor = '#f59e0b';
                badgeText = 'Backend online (No AI)';
                titleText = `Backend is online, but AI provider (${ms?.provider || 'local'}) is not responding.`;
              }

              return (
                <div className="status-badge" title={titleText} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                  <div className="status-dot" style={{ backgroundColor: dotColor }} />
                  <span className="status-badge-text" style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {badgeText}
                  </span>
                </div>
              );
            })()}
          </div>
        </div>

        <div className="main-content">
          {health === 'offline' && (
            <div style={{ backgroundColor: 'var(--bg-card)', border: '1px solid #ef4444', borderRadius: 8, padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 10, color: '#f87171', marginBottom: 24 }}>
              <AlertCircle size={20} />
              <span>The Studio backend is not answering on this port. Nothing below is live until it is back.</span>
            </div>
          )}

          {tab === 'studio_chat' && <StudioChat />}
          {tab === 'dashboard' && <Dashboard />}
          {tab === 'projects' && <Projects />}
          {tab === 'topic_vault' && <TopicVault />}
          {tab === 'board' && <Board />}
          {tab === 'analyze' && <Analyze />}
          {tab === 'research' && <Research />}
          {tab === 'music' && <Music />}
          {tab === 'writing_style' && <WritingStyle />}
          {tab === 'scheduler_desk' && <SchedulerDesk />}
          {bulkEditOpened && <div hidden={tab !== 'bulk_edit'}><BulkEdit /></div>}
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
          {tab === 'departments' && <Departments />}
          {tab === 'health' && <Health />}
          {tab === 'settings' && <Settings />}
          {tab === 'logs' && <Logs />}
        </div>
      </div>

      {showTop && (
        <button
          type="button"
          onClick={() => workspaceRef.current?.scrollTo({ top: 0, behavior: 'smooth' })}
          style={{ position: 'fixed', bottom: 32, right: 32, zIndex: 999, width: 46, height: 46, borderRadius: '50%', background: 'var(--accent-gradient)', color: 'var(--text-on-accent)', border: 'none', boxShadow: 'var(--card-shadow)', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
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
    <ThemeProvider>
      <StudioProvider>
        <Shell />
      </StudioProvider>
    </ThemeProvider>
  );
}
