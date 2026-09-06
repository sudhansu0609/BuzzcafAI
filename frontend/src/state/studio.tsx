import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { apiFetch } from '../services/http';
import { ConfirmDialog, ToastHost, type ConfirmRequest } from '../components/Toast';
import type { HealthInfo, Project, StudioSettings, TabId, ToastItem, ToastKind, WorkflowInfo } from '../lib/types';

// Shared Studio state: what every page needs and none should refetch on its
// own - the brand list, projects, settings, backend health - plus navigation,
// toasts and an in-app confirm. Pages read it through useStudio().

interface StudioContextValue {
  tab: TabId;
  navigate: (tab: TabId) => void;

  health: 'unknown' | 'online' | 'offline';
  healthInfo: HealthInfo | null;
  brands: string[];
  workflows: WorkflowInfo[];
  projects: Project[];
  settings: StudioSettings | null;
  selectedChannel: string;
  setSelectedChannel: (channel: string) => void;

  refreshProjects: () => Promise<void>;
  refreshSettings: () => Promise<void>;
  refreshHealth: () => Promise<void>;

  toast: (text: string, kind?: ToastKind) => void;
  confirm: (request: ConfirmRequest) => Promise<boolean>;

  // Group chat needs the agent ids picked in the creator page.
  groupChatAgentIds: string[];
  setGroupChatAgentIds: (ids: string[]) => void;
}

const StudioContext = createContext<StudioContextValue | null>(null);

const CHANNEL_KEY = 'buzzcaf_selected_channel';
const TAB_KEY = 'buzzcaf_active_tab';
const HEALTH_POLL_MS = 15_000;

function readStorage(key: string, fallback: string): string {
  try {
    return localStorage.getItem(key) || fallback;
  } catch {
    return fallback;
  }
}

function writeStorage(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // Storage may be unavailable; the app works without it.
  }
}

export function StudioProvider({ children }: { children: ReactNode }) {
  const [tab, setTab] = useState<TabId>(() => (readStorage(TAB_KEY, 'studio_chat') as TabId) || 'studio_chat');
  const [health, setHealth] = useState<'unknown' | 'online' | 'offline'>('unknown');
  const [healthInfo, setHealthInfo] = useState<HealthInfo | null>(null);
  const [brands, setBrands] = useState<string[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowInfo[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [settings, setSettings] = useState<StudioSettings | null>(null);
  const [selectedChannel, setSelectedChannelState] = useState<string>(() => readStorage(CHANNEL_KEY, 'Beyond3Baje'));
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [confirmRequest, setConfirmRequest] = useState<ConfirmRequest | null>(null);
  const confirmResolver = useRef<((yes: boolean) => void) | null>(null);
  const [groupChatAgentIds, setGroupChatAgentIds] = useState<string[]>([]);

  const navigate = useCallback((next: TabId) => {
    setTab(next);
    writeStorage(TAB_KEY, next);
  }, []);

  const setSelectedChannel = useCallback((channel: string) => {
    setSelectedChannelState(channel);
    writeStorage(CHANNEL_KEY, channel);
  }, []);

  const toast = useCallback((text: string, kind: ToastKind = 'info') => {
    const id = `t-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setToasts((prev) => [...prev, { id, kind, text }]);
    window.setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), kind === 'error' ? 7000 : 4000);
  }, []);

  const dismissToast = useCallback((id: string) => setToasts((prev) => prev.filter((t) => t.id !== id)), []);

  const confirm = useCallback((request: ConfirmRequest) => {
    return new Promise<boolean>((resolve) => {
      confirmResolver.current = resolve;
      setConfirmRequest(request);
    });
  }, []);

  const answerConfirm = useCallback((yes: boolean) => {
    setConfirmRequest(null);
    confirmResolver.current?.(yes);
    confirmResolver.current = null;
  }, []);

  const refreshHealth = useCallback(async () => {
    try {
      const res = await apiFetch('/health', { signal: AbortSignal.timeout(4000) });
      if (!res.ok) throw new Error(String(res.status));
      const data = (await res.json()) as HealthInfo;
      setHealthInfo(data);
      setHealth('online');
    } catch {
      setHealthInfo(null);
      setHealth('offline');
    }
  }, []);

  const refreshProjects = useCallback(async () => {
    try {
      const res = await apiFetch('/api/projects');
      if (!res.ok) throw new Error(`Projects request failed (${res.status})`);
      const data = await res.json();
      setProjects(Array.isArray(data) ? data : []);
    } catch (err) {
      // No invented projects: an unreachable backend shows an empty list and
      // the offline badge, never three fake productions.
      console.warn('Could not load projects', err);
    }
  }, []);

  const refreshSettings = useCallback(async () => {
    try {
      const res = await apiFetch('/api/settings');
      if (res.ok) setSettings(await res.json());
    } catch (err) {
      console.warn('Could not load settings', err);
    }
  }, []);

  const loadStatic = useCallback(async () => {
    try {
      const res = await apiFetch('/api/brands');
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) setBrands(data.filter((b) => typeof b === 'string'));
      }
    } catch (err) {
      console.warn('Could not load brands', err);
    }
    try {
      const res = await apiFetch('/api/workflows');
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) setWorkflows(data);
      }
    } catch (err) {
      console.warn('Could not load workflows', err);
    }
  }, []);

  useEffect(() => {
    refreshHealth();
    loadStatic();
    refreshProjects();
    refreshSettings();
    const timer = window.setInterval(refreshHealth, HEALTH_POLL_MS);
    return () => window.clearInterval(timer);
  }, [refreshHealth, loadStatic, refreshProjects, refreshSettings]);

  const value = useMemo<StudioContextValue>(
    () => ({
      tab,
      navigate,
      health,
      healthInfo,
      brands,
      workflows,
      projects,
      settings,
      selectedChannel,
      setSelectedChannel,
      refreshProjects,
      refreshSettings,
      refreshHealth,
      toast,
      confirm,
      groupChatAgentIds,
      setGroupChatAgentIds,
    }),
    [
      tab, navigate, health, healthInfo, brands, workflows, projects, settings, selectedChannel,
      setSelectedChannel, refreshProjects, refreshSettings, refreshHealth, toast, confirm, groupChatAgentIds,
    ],
  );

  return (
    <StudioContext.Provider value={value}>
      {children}
      <ToastHost toasts={toasts} onDismiss={dismissToast} />
      <ConfirmDialog request={confirmRequest} onAnswer={answerConfirm} />
    </StudioContext.Provider>
  );
}

export function useStudio(): StudioContextValue {
  const ctx = useContext(StudioContext);
  if (!ctx) throw new Error('useStudio must be used inside <StudioProvider>');
  return ctx;
}
