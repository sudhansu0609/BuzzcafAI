import React from 'react';
import { Bot, MessageSquare, Cpu, Sparkles, Volume2, Lock, ShieldCheck, User } from 'lucide-react';
import { ModelsStatusResponse } from '../types/agent';
import { UserProfile } from '../services/UserService';

interface HeaderProps {
  activeTab: 'creator' | 'chat';
  setActiveTab: (tab: 'creator' | 'chat') => void;
  modelsStatus: ModelsStatusResponse | null;
  authStatus?: { authEnabled: boolean; hasGlobalPassword?: boolean; isAuthenticated: boolean; authenticatedUserId?: string } | null;
  onOpenAuthSettings?: () => void;
  activeUser: UserProfile;
  onOpenUserDashboard: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  activeTab,
  setActiveTab,
  modelsStatus,
  authStatus,
  onOpenAuthSettings,
  activeUser,
  onOpenUserDashboard
}) => {
  const isOnline = modelsStatus?.lmStudioOnline || modelsStatus?.ollamaOnline;
  const isProtected = authStatus?.authEnabled;

  return (
    <header className="app-header">
      <div className="brand-logo">
        <div className="logo-icon">
          <Volume2 size={24} color="#ffffff" />
        </div>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span className="brand-title">MidnightBuzz</span>
            <span className="brand-badge">Agent Studio</span>
          </div>
          <span style={{ fontSize: '12px', color: 'var(--text-dim)' }}>
            100% Local AI Models & Zero-Shot Voice Cloning
          </span>
        </div>
      </div>

      <nav className="nav-tabs">
        <button
          className={`nav-btn ${activeTab === 'creator' ? 'active' : ''}`}
          onClick={() => setActiveTab('creator')}
          id="nav-creator-btn"
        >
          <Sparkles size={18} />
          Agent Creator Studio
        </button>
        <button
          className={`nav-btn ${activeTab === 'chat' ? 'active' : ''}`}
          onClick={() => setActiveTab('chat')}
          id="nav-chat-btn"
        >
          <MessageSquare size={18} />
          Voice Chatroom Workspace
        </button>
      </nav>

      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        {/* User Account Dashboard Pill */}
        <button
          type="button"
          onClick={onOpenUserDashboard}
          style={{
            background: 'linear-gradient(135deg, #1e293b 0%, #0f172a 100%)',
            color: '#ffffff',
            border: '1px solid rgba(148, 163, 184, 0.4)',
            padding: '6px 14px',
            borderRadius: '12px',
            fontSize: '12px',
            fontWeight: 700,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            boxShadow: '0 2px 8px rgba(0,0,0,0.1)'
          }}
          title="Switch User Workspace / Open User Dashboard"
        >
          <span style={{ fontSize: '15px' }}>{activeUser.avatarIcon || '👤'}</span>
          <span>{activeUser.name}</span>
          <span style={{ fontSize: '10px', background: 'rgba(99, 102, 241, 0.3)', color: '#c7d2fe', padding: '1px 6px', borderRadius: '6px' }}>Switch User / Login</span>
        </button>

        {onOpenAuthSettings && (
          <button
            type="button"
            onClick={onOpenAuthSettings}
            style={{
              background: isProtected ? '#0f172a' : '#f1f5f9',
              color: isProtected ? '#ffffff' : '#0f172a',
              border: '1px solid #cbd5e1',
              padding: '6px 12px',
              borderRadius: '10px',
              fontSize: '12px',
              fontWeight: 700,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
            title="Password & Access Security Settings"
          >
            {isProtected ? <Lock size={14} color="#38bdf8" /> : <ShieldCheck size={14} />}
            {isProtected ? 'Password Protected' : 'Security Lock'}
          </button>
        )}

        <div className="engine-status-pill">
          <Cpu size={16} color="var(--accent-secondary)" />
          <span>Local Models:</span>
          <span className={`status-dot ${isOnline ? 'online' : 'offline'}`} />
          <span style={{ color: isOnline ? 'var(--accent-green)' : 'var(--accent-amber)' }}>
            {isOnline ? 'LM Studio Connected' : 'Preset Standalone Mode'}
          </span>
        </div>
      </div>
    </header>
  );
};
