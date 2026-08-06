import { Agent, ModelsStatusResponse, ChatMessage } from '../types/agent';

const API_BASE = '/api';

export function getAuthToken(): string | null {
  return localStorage.getItem('midnightbuzz_auth_token');
}

export function setAuthToken(token: string | null) {
  if (token) {
    localStorage.setItem('midnightbuzz_auth_token', token);
  } else {
    localStorage.removeItem('midnightbuzz_auth_token');
  }
}

import { UserService } from './UserService';

export function getAuthHeaders(): Record<string, string> {
  const token = getAuthToken();
  const activeUser = UserService.getActiveUser();
  const headers: Record<string, string> = {
    'X-User-ID': activeUser.id
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

export async function fetchAuthStatus(): Promise<{ authEnabled: boolean; hasGlobalPassword: boolean; isAuthenticated: boolean; authenticatedUserId?: string }> {
  const res = await fetch(`${API_BASE}/auth/status`, {
    headers: { ...getAuthHeaders() }
  });
  if (!res.ok) return { authEnabled: false, hasGlobalPassword: false, isAuthenticated: true };
  return res.json();
}

export async function fetchServerUsers(): Promise<Array<{ id: string; name: string; role: string; avatarIcon: string; badgeColor: string; hasPassword: boolean }>> {
  const res = await fetch(`${API_BASE}/auth/users`, {
    headers: { ...getAuthHeaders() }
  });
  if (!res.ok) return [];
  return res.json();
}

export async function loginUser(userId?: string, password?: string): Promise<{ success: boolean; token: string; user: any; message: string }> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ userId, password })
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Login failed' }));
    throw new Error(err.detail || 'Login failed');
  }
  const data = await res.json();
  if (data.token) {
    setAuthToken(data.token);
  }
  return data;
}

export async function registerUser(name: string, role?: string, avatarIcon?: string, password?: string): Promise<{ success: boolean; token: string; user: any; message: string }> {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, role, avatarIcon, password })
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Registration failed' }));
    throw new Error(err.detail || 'Registration failed');
  }
  const data = await res.json();
  if (data.token) {
    setAuthToken(data.token);
  }
  return data;
}

export async function setPassword(newPassword: string, currentPassword?: string, authEnabled = true, userId?: string) {
  const res = await fetch(`${API_BASE}/auth/set-password`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ newPassword, currentPassword, authEnabled, userId })
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to set password' }));
    throw new Error(err.detail || 'Failed to set password');
  }
  const data = await res.json();
  if (data.token) {
    setAuthToken(data.token);
  }
  return data;
}

export async function toggleAuth(authEnabled: boolean) {
  const res = await fetch(`${API_BASE}/auth/toggle`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({ authEnabled })
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to toggle auth' }));
    throw new Error(err.detail || 'Failed to toggle auth');
  }
  return res.json();
}

export async function logoutUser() {
  await fetch(`${API_BASE}/auth/logout`, {
    method: 'POST',
    headers: { ...getAuthHeaders() }
  }).catch(() => {});
  setAuthToken(null);
}

export async function fetchAgents(): Promise<Agent[]> {
  const res = await fetch(`${API_BASE}/agents`, {
    headers: { ...getAuthHeaders() }
  });
  if (!res.ok) throw new Error('Failed to fetch agents');
  return res.json();
}

export async function createAgent(agent: Agent): Promise<Agent> {
  const res = await fetch(`${API_BASE}/agents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(agent),
  });
  if (!res.ok) throw new Error('Failed to create agent');
  return res.json();
}

export async function updateAgent(agent: Agent): Promise<Agent> {
  const res = await fetch(`${API_BASE}/agents/${agent.id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify(agent),
  });
  if (!res.ok) throw new Error('Failed to update agent');
  return res.json();
}

export async function deleteAgent(agentId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/agents/${agentId}`, {
    method: 'DELETE',
    headers: { ...getAuthHeaders() }
  });
  if (!res.ok) throw new Error('Failed to delete agent');
}

export async function fetchModelsStatus(): Promise<ModelsStatusResponse> {
  const res = await fetch(`${API_BASE}/models`, {
    headers: { ...getAuthHeaders() }
  });
  if (!res.ok) {
    return {
      lmStudioOnline: false,
      ollamaOnline: false,
      models: [
        { id: 'qwen2.5-coder', name: 'Qwen 2.5 Coder', provider: 'Local Preset', online: false },
        { id: 'llama-3.2-3b', name: 'Llama 3.2 3B', provider: 'Local Preset', online: false },
        { id: 'deepseek-r1-8b', name: 'DeepSeek R1 8B', provider: 'Local Preset', online: false },
      ]
    };
  }
  return res.json();
}

export async function uploadVoiceSample(file: File) {
  const formData = new FormData();
  formData.append('file', file);

  const res = await fetch(`${API_BASE}/agents/clone-voice`, {
    method: 'POST',
    headers: { ...getAuthHeaders() },
    body: formData,
  });
  if (!res.ok) throw new Error('Voice cloning failed');
  return res.json();
}

export async function sendChatMessage(
  agentId: string,
  userMessage: string,
  history: ChatMessage[],
  groupAgentIds?: string[]
) {
  const chatHistory = history.map(h => ({
    role: h.role,
    content: h.content,
  }));

  const res = await fetch(`${API_BASE}/chat/completions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({
      agentId,
      userMessage,
      chatHistory,
      groupAgentIds,
    }),
  });

  if (!res.ok) throw new Error('Chat completion failed');
  return res.json();
}

export async function streamChat(
  agentId: string,
  userMessage: string,
  history: ChatMessage[],
  model?: string,
  onToken?: (token: string) => void,
  onAudioChunk?: (audioBase64: string, text: string, mediaType: string) => void,
  onDone?: (fullText: string) => void,
  onError?: (error: string) => void
): Promise<void> {
  const chatHistory = history.map(h => ({
    role: h.role,
    content: h.content,
  }));

  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
    body: JSON.stringify({
      agent_id: agentId,
      message: userMessage,
      chat_history: chatHistory,
      model,
    }),
  });

  if (!res.ok) {
    onError?.(`HTTP ${res.status}`);
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) {
    onError?.('No reader');
    return;
  }

  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const data = JSON.parse(line.slice(6));
          if (data.type === 'token') {
            onToken?.(data.content);
          } else if (data.type === 'audio_chunk') {
            onAudioChunk?.(data.audio, data.text, data.media_type || 'audio/wav');
          } else if (data.type === 'done') {
            onDone?.(data.full_text);
          } else if (data.type === 'error') {
            onError?.(data.message);
          }
        } catch (e) {
          // skip malformed JSON
        }
      }
    }
  } catch (e) {
    onError?.(`Stream error: ${e}`);
  } finally {
    reader.releaseLock();
  }
}

export function getAudioStreamUrl(text: string, pitch = 1.0, rate = 1.0, agentId?: string, samplePath?: string, voiceModel?: string): string {
  const params = new URLSearchParams({ text, pitch: pitch.toString(), rate: rate.toString() });
  if (agentId) params.append('agent_id', agentId);
  if (samplePath) params.append('sample_path', samplePath);
  if (voiceModel) params.append('voice_model', voiceModel);
  const token = getAuthToken();
  if (token) params.append('token', token);
  params.append('_t', Date.now().toString());
  return `${API_BASE}/tts/stream?${params.toString()}`;
}
