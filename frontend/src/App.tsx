import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { AgentCreatorStudio } from './pages/ai/AgentCreatorStudio';
import { AgentsGroupChat } from './pages/ai/AgentsGroupChat';
import { AuthModal } from './components/AuthModal';
import { UserDashboardModal } from './components/UserDashboardModal';
import { Agent, ModelsStatusResponse } from './types/agent';
import { fetchAgents, fetchModelsStatus, fetchAuthStatus } from './services/api';
import { UserService, UserProfile } from './services/UserService';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'creator' | 'chat'>('creator');
  const [agents, setAgents] = useState<Agent[]>([]);
  const [modelsStatus, setModelsStatus] = useState<ModelsStatusResponse | null>(null);
  const [chatSelectedAgentId, setChatSelectedAgentId] = useState<string | null>(null);

  // User State
  const [activeUser, setActiveUser] = useState<UserProfile>(UserService.getActiveUser());
  const [showUserModal, setShowUserModal] = useState(false);

  // Auth State
  const [authStatus, setAuthStatus] = useState<{ authEnabled: boolean; hasGlobalPassword?: boolean; isAuthenticated: boolean; authenticatedUserId?: string } | null>(null);
  const [showSettingsModal, setShowSettingsModal] = useState(false);

  const checkAuthAndLoad = async () => {
    try {
      const auth = await fetchAuthStatus();
      setAuthStatus(auth);

      if (auth.isAuthenticated) {
        loadData();
      }
    } catch (err) {
      console.error('Failed to check auth status:', err);
    }
  };

  const loadData = async () => {
    try {
      const agentsList = await fetchAgents();
      setAgents(agentsList);

      const status = await fetchModelsStatus();
      setModelsStatus(status);
    } catch (err) {
      console.error('Failed to load initial MidnightBuzz data:', err);
    }
  };

  useEffect(() => {
    checkAuthAndLoad();

    const handleUserChanged = () => {
      const newUser = UserService.getActiveUser();
      setActiveUser(newUser);
      loadData();
    };

    window.addEventListener('midnightbuzz_user_changed', handleUserChanged);
    return () => {
      window.removeEventListener('midnightbuzz_user_changed', handleUserChanged);
    };
  }, []);

  const handleSelectAgentForChat = (agentId: string, autoSwitchTab = false) => {
    setChatSelectedAgentId(agentId);
    if (autoSwitchTab) {
      setActiveTab('chat');
    }
  };

  const handleAuthSuccess = async () => {
    await checkAuthAndLoad();
  };

  const handleUserSwitch = (user: UserProfile) => {
    setActiveUser(user);
    loadData();
  };

  const requiresLogin = authStatus?.authEnabled && !authStatus?.isAuthenticated;

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        modelsStatus={modelsStatus}
        authStatus={authStatus}
        onOpenAuthSettings={() => setShowSettingsModal(true)}
        activeUser={activeUser}
        onOpenUserDashboard={() => setShowUserModal(true)}
      />

      {requiresLogin && authStatus && (
        <AuthModal
          mode="login"
          authStatus={authStatus}
          onSuccess={handleAuthSuccess}
        />
      )}

      {showSettingsModal && authStatus && (
        <AuthModal
          mode="settings"
          authStatus={authStatus}
          onSuccess={handleAuthSuccess}
          onClose={() => setShowSettingsModal(false)}
        />
      )}

      {showUserModal && (
        <UserDashboardModal
          onClose={() => setShowUserModal(false)}
          onUserChanged={handleUserSwitch}
        />
      )}

      <main className="app-container" style={{ flex: 1 }}>
        {activeTab === 'creator' ? (
          <AgentCreatorStudio
            key={activeUser.id}
            agents={agents}
            availableModels={modelsStatus?.models || []}
            onAgentsUpdated={loadData}
            onSelectAgentForChat={handleSelectAgentForChat}
          />
        ) : (
          <AgentsGroupChat
            key={activeUser.id}
            agents={agents}
            initialAgentId={chatSelectedAgentId}
            onAgentsUpdated={loadData}
          />
        )}
      </main>
    </div>
  );
};

export default App;
