export interface VoiceProfile {
  voiceId: string;
  name: string;
  samplePath?: string | null;
  pitch: number;
  rate: number;
  cloned: boolean;
  clonedVoiceBase?: string;
}

// Face anchor points for the photo-realistic avatar, normalized 0..1 against
// the photo's natural width/height so they survive any crop or resize.
export interface FaceLandmarks {
  leftEye: { x: number; y: number };
  rightEye: { x: number; y: number };
  mouth: { x: number; y: number };
  /** Mouth width as a fraction of the image width. */
  mouthWidth: number;
}

// Configuration for the animated persona avatar. Every field is a plain
// value so it serializes straight onto the agent record.
export interface AvatarConfig {
  /** 'photo' animates a real portrait; 'cartoon' (default) uses the SVG persona. */
  mode?: 'cartoon' | 'photo';
  /** Portrait dataURL for photo mode (downscaled at upload time). */
  photoUrl?: string;
  landmarks?: FaceLandmarks;
  /** Photo-mode animation intensity multipliers (1 = default, 0 = off). */
  mouthMotion?: number;
  headMotion?: number;
  exprMotion?: number;
  skinTone: string;
  hairStyle: 'short' | 'long' | 'bun' | 'curly' | 'spiky' | 'bald';
  hairColor: string;
  eyeColor: string;
  shirtColor: string;
  accessory: 'none' | 'glasses' | 'earrings' | 'both';
  bgColor: string;
}

export interface Agent {
  id: string;
  name: string;
  role: string;
  avatar: string;
  avatarIcon: string;
  avatarImage?: string;
  avatarConfig?: AvatarConfig;
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
