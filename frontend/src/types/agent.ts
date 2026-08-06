export interface VoiceProfile {
  voiceId: string;
  name: string;
  samplePath?: string | null;
  pitch: number;
  rate: number;
  cloned: boolean;
  clonedVoiceBase?: string;
}

export interface Agent {
  id: string;
  name: string;
  role: string;
  avatar: string;
  avatarIcon: string;
  avatarImage?: string;
  personaTag: string;
  systemPrompt: string;
  temperature: number;
  topP: number;
  maxTokens: number;
  responseStyle: 'Concise' | 'Verbose' | 'Hinglish' | 'Formal';
  responseLanguage?: 'Hinglish' | 'Hindi';
  voiceEnabled?: boolean;
  modelMapping: string;
  voiceProfile: VoiceProfile;
  createdAt?: string;
}

export interface LocalModel {
  id: string;
  name: string;
  provider: string;
  online: boolean;
}

export interface ModelsStatusResponse {
  lmStudioOnline: boolean;
  ollamaOnline: boolean;
  models: LocalModel[];
}

export interface GroupResponse {
  agentId: string;
  agentName: string;
  avatar: string;
  avatarIcon: string;
  avatarImage?: string;
  text: string;
}

export interface ChatMessage {
  id: string;
  senderId: string;
  senderName: string;
  senderAvatar: string;
  senderAvatarIcon: string;
  senderAvatarImage?: string;
  role: 'user' | 'agent';
  content: string;
  timestamp: string;
  isVoicePlaying?: boolean;
  groupResponses?: GroupResponse[];
}
