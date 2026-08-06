import React, { useState, useEffect, useRef } from 'react';
import { Agent, ChatMessage } from '../../types/agent';
import { sendChatMessage, getAudioStreamUrl, getAuthHeaders, updateAgent, streamChat } from '../../services/api';
import { Mic, Send, Users, User, Volume2, VolumeX, Square, Play, RefreshCw, Radio, Trash2, Languages } from 'lucide-react';

interface AgentsGroupChatProps {
  agents: Agent[];
  initialAgentId?: string | null;
  onAgentsUpdated?: () => void;
}

import { UserService } from '../../services/UserService';

export const AgentsGroupChat: React.FC<AgentsGroupChatProps> = ({ agents, initialAgentId, onAgentsUpdated }) => {
  const activeUser = UserService.getActiveUser();
  const chatStorageKey = `midnightbuzz_chat_history_${activeUser.id}`;

  const [chatMode, setChatMode] = useState<'single' | 'group'>('single');
  const [selectedAgentId, setSelectedAgentId] = useState<string>(initialAgentId || agents[0]?.id || '');
  const [groupSelectedAgentIds, setGroupSelectedAgentIds] = useState<string[]>(agents.map(a => a.id));
  const [agentLanguageMap, setAgentLanguageMap] = useState<Record<string, 'Hindi' | 'Hinglish'>>({});

  useEffect(() => {
    if (initialAgentId) {
      setSelectedAgentId(initialAgentId);
    }
  }, [initialAgentId]);

  const [inputMessage, setInputMessage] = useState('');
  
  // Persistent Chat History initialization from localStorage
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    try {
      const saved = localStorage.getItem(`midnightbuzz_chat_history_${UserService.getActiveUser().id}`);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) {
          return parsed;
        }
      }
    } catch (e) {
      console.error("Failed to load saved chat history:", e);
    }
    return [];
  });
  
  const [isLoading, setIsLoading] = useState(false);
  const [thinkingMessage, setThinkingMessage] = useState<string | null>(null);

  const chatFeedRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (chatFeedRef.current) {
      chatFeedRef.current.scrollTo({
        top: chatFeedRef.current.scrollHeight,
        behavior: 'smooth'
      });
    }
  }, [messages, isLoading, thinkingMessage]);

  // Audio controls
  const [isHandsFreeListening, setIsHandsFreeListening] = useState(false);
  const [audioSpeed, setAudioSpeed] = useState<number>(1.0);
  const [isMuted, setIsMuted] = useState(false);
  const [playingMessageId, setPlayingMessageId] = useState<string | null>(null);
  const [speechLang, setSpeechLang] = useState<string>('hi-IN');

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const recognitionRef = useRef<any>(null);
  const isListeningRef = useRef<boolean>(false);
  const isAgentSpeakingRef = useRef<boolean>(false);
  const silenceTimerRef = useRef<any>(null);
  const currentSpeechBufferRef = useRef<string>('');

  // Streaming state: accumulate tokens in real-time, queue audio chunks for playback
  const streamingTextRef = useRef<string>('');
  const audioQueueRef = useRef<Array<{ base64: string, mediaType: string }>>([]);
  const isPlayingChunkRef = useRef<boolean>(false);
  const isStreamingRef = useRef<boolean>(false);
  const [streamingMessageId, setStreamingMessageId] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState<string>('');

  // Sequential audio chunk player: plays base64 WAV chunks one after another
  const playNextChunk = (messageId?: string) => {
    if (audioQueueRef.current.length === 0) {
      isPlayingChunkRef.current = false;
      setPlayingMessageId(null);
      isAgentSpeakingRef.current = false;
      if (isListeningRef.current) {
        setTimeout(() => safeRestartListening(), 300);
      }
      return;
    }

    isPlayingChunkRef.current = true;
    const chunk = audioQueueRef.current.shift()!;
    try {
      const byteString = atob(chunk.base64);
      const byteArray = new Uint8Array(byteString.length);
      for (let i = 0; i < byteString.length; i++) byteArray[i] = byteString.charCodeAt(i);
      const blob = new Blob([byteArray], { type: chunk.mediaType || 'audio/wav' });
      
      // Skip tiny silent WAVs (< 100 bytes)
      if (blob.size < 100) {
        playNextChunk(messageId);
        return;
      }
      
      const blobUrl = URL.createObjectURL(blob);
      const audio = new Audio(blobUrl);
      audio.playbackRate = audioSpeed;
      audioRef.current = audio;

      audio.onended = () => {
        URL.revokeObjectURL(blobUrl);
        playNextChunk(messageId);
      };
      audio.onerror = () => {
        URL.revokeObjectURL(blobUrl);
        playNextChunk(messageId);
      };
      audio.play().catch(() => {
        URL.revokeObjectURL(blobUrl);
        playNextChunk(messageId);
      });
    } catch (e) {
      playNextChunk(messageId);
    }
  };

  const enqueueAudioChunk = (base64: string, _text: string, mediaType: string, messageId?: string) => {
    audioQueueRef.current.push({ base64, mediaType });
    if (messageId) setPlayingMessageId(messageId);
    isAgentSpeakingRef.current = true;
    if (recognitionRef.current) {
      try { recognitionRef.current.abort(); } catch(e) {}
    }
    // If not currently playing, start the queue
    if (!isPlayingChunkRef.current) {
      playNextChunk(messageId);
    }
  };

  useEffect(() => {
    isListeningRef.current = isHandsFreeListening;
  }, [isHandsFreeListening]);

  useEffect(() => {
    initSpeechRecognition(speechLang);
    return () => {
      if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
      if (recognitionRef.current) {
        try { recognitionRef.current.stop(); } catch(e) {}
      }
    };
  }, [speechLang]);

  const initSpeechRecognition = (targetLang?: string) => {
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
      const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      
      if (recognitionRef.current) {
        try { recognitionRef.current.stop(); } catch(e) {}
      }

      const recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = targetLang || speechLang || 'hi-IN';

      recognition.onresult = (event: any) => {
        let transcript = '';
        for (let i = 0; i < event.results.length; i++) {
          transcript += event.results[i][0].transcript;
        }
        const trimmed = transcript.trim();
        if (trimmed) {
          setInputMessage(trimmed);
          currentSpeechBufferRef.current = trimmed;

          // Reset 2.0-second silence timer whenever user is actively speaking
          if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);
          silenceTimerRef.current = setTimeout(() => {
            if (currentSpeechBufferRef.current && isListeningRef.current) {
              const textToSend = currentSpeechBufferRef.current;
              currentSpeechBufferRef.current = '';
              setInputMessage('');
              handleSendMessage(textToSend);
            }
          }, 2000);
        }
      };

      recognition.onerror = (e: any) => {
        console.error("Speech Recognition Notice:", e);
        if (e.error === 'not-allowed') {
          setIsHandsFreeListening(false);
          isListeningRef.current = false;
        }
      };

      recognition.onend = () => {
        if (isListeningRef.current && !isAgentSpeakingRef.current && recognitionRef.current) {
          try {
            recognitionRef.current.start();
          } catch(e) {
            console.log("Auto-restart recognition notice:", e);
          }
        }
      };

      recognitionRef.current = recognition;
    }
  };

  const toggleListening = () => {
    if (!recognitionRef.current) {
      alert("Continuous Speech Recognition is not natively supported in this browser. Please use Chrome or Edge.");
      return;
    }

    if (silenceTimerRef.current) clearTimeout(silenceTimerRef.current);

    if (isHandsFreeListening) {
      isListeningRef.current = false;
      setIsHandsFreeListening(false);
      try { recognitionRef.current.stop(); } catch(e) {}
    } else {
      isListeningRef.current = true;
      setIsHandsFreeListening(true);
      try { recognitionRef.current.start(); } catch(e) {}
    }
  };

  // Auto-save messages to localStorage whenever messages state changes
  useEffect(() => {
    if (messages.length > 0) {
      try {
        localStorage.setItem(chatStorageKey, JSON.stringify(messages));
      } catch (e) {
        console.error("Failed to save chat history:", e);
      }
    }
  }, [messages, chatStorageKey]);

  useEffect(() => {
    if (messages.length === 0 && agents.length > 0) {
      const welcome: ChatMessage = {
        id: 'welcome-msg',
        senderId: 'system',
        senderName: 'MidnightBuzz System',
        senderAvatar: 'linear-gradient(135deg, #6366f1 0%, #06b6d4 100%)',
        senderAvatarIcon: '🎙️',
        role: 'agent',
        content: `Welcome to ${activeUser.name}'s Private MidnightBuzz Voice Chatroom! Choose 1-on-1 Voice Chat or Multi-Agent Group Mode to start brainstorming.`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };
      setMessages([welcome]);
      try {
        localStorage.setItem(chatStorageKey, JSON.stringify([welcome]));
      } catch (e) {}
    }
  }, [agents, chatStorageKey]);

  // Explicit Clear Chat History
  const handleClearChatHistory = () => {
    stopAllVoiceAudio();
    try {
      localStorage.removeItem(chatStorageKey);
    } catch (e) {}
    
    const welcome: ChatMessage = {
      id: `welcome-${Date.now()}`,
      senderId: 'system',
      senderName: 'MidnightBuzz System',
      senderAvatar: 'linear-gradient(135deg, #6366f1 0%, #06b6d4 100%)',
      senderAvatarIcon: '🎙️',
      role: 'agent',
      content: 'Welcome to the MidnightBuzz Voice Chatroom Studio! Choose 1-on-1 Voice Chat or Multi-Agent Group Mode to start brainstorming.',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };
    setMessages([welcome]);
    try {
      localStorage.setItem(chatStorageKey, JSON.stringify([welcome]));
    } catch (e) {}
  };

  // Determine gender-specific thinking text: "Soch raha hu... Ek minute" (Male) vs "Soch rahi hu... Ek minute" (Female)
  const getAgentThinkingText = (targetAgent?: Agent): string => {
    if (!targetAgent) return "Soch raha hu... Ek minute";

    const nameLower = (targetAgent.name || '').toLowerCase();
    const roleLower = (targetAgent.role || '').toLowerCase();
    const voiceLower = (targetAgent.voiceProfile?.clonedVoiceBase || '').toLowerCase();
    const voiceIdLower = (targetAgent.voiceProfile?.voiceId || '').toLowerCase();

    const isFemale = 
      nameLower.includes('ananya') ||
      nameLower.includes('shilpi') ||
      nameLower.includes('swara') ||
      nameLower.includes('neerja') ||
      nameLower.includes('kavyanjali') ||
      nameLower.includes('female') ||
      nameLower.includes('woman') ||
      nameLower.includes('girl') ||
      roleLower.includes('female') ||
      roleLower.includes('woman') ||
      voiceLower.includes('female') ||
      voiceLower.includes('swara') ||
      voiceLower.includes('neerja') ||
      voiceLower.includes('aria') ||
      voiceLower.includes('ana') ||
      voiceIdLower.includes('swara') ||
      voiceIdLower.includes('neerja') ||
      voiceIdLower.includes('aria');

    return isFemale ? "Soch rahi hu... Ek minute" : "Soch raha hu... Ek minute";
  };

  // Silent Announcement for Thinking Status per user preference
  const announceThinkingAudio = (_text: string, _targetAgent?: Agent) => {
    return; // Keep thinking phrase audio completely silent
  };

  // Visualizer canvas loop
  useEffect(() => {
    if (isHandsFreeListening && canvasRef.current) {
      const canvas = canvasRef.current;
      const ctx = canvas.getContext('2d');
      let step = 0;

      const draw = () => {
        if (!ctx) return;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = 'rgba(139, 92, 246, 0.2)';
        
        const bars = 30;
        const barWidth = canvas.width / bars;

        for (let i = 0; i < bars; i++) {
          const height = Math.sin(step * 0.1 + i * 0.4) * 20 + 25;
          ctx.fillRect(i * barWidth, canvas.height - height, barWidth - 2, height);
        }

        step++;
        animationFrameRef.current = requestAnimationFrame(draw);
      };

      draw();
    } else if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
    }
  }, [isHandsFreeListening]);

  const stopAllVoiceAudio = () => {
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
    setPlayingMessageId(null);
  };

  const handleSendMessage = async (customText?: string) => {
    const textToSend = customText || inputMessage;
    if (!textToSend.trim() || isLoading) return;

    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}`,
      senderId: 'user',
      senderName: 'You',
      senderAvatar: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
      senderAvatarIcon: '👤',
      role: 'user',
      content: textToSend,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setMessages(prev => [...prev, userMsg]);
    setInputMessage('');
    
    const targetAgentId = selectedAgentId || agents[0]?.id;
    const targetAgent = agents.find(a => a.id === targetAgentId);
    const thinkingTxt = getAgentThinkingText(targetAgent);
    
    setThinkingMessage(thinkingTxt);
    announceThinkingAudio(thinkingTxt, targetAgent);
    setIsLoading(true);

    const agentMsgId = `msg-agent-${Date.now()}`;
    const mainAgent = targetAgent;

    const agentMsg: ChatMessage = {
      id: agentMsgId,
      senderId: targetAgentId,
      senderName: mainAgent?.name || 'Agent',
      senderAvatar: mainAgent?.avatar || 'linear-gradient(135deg, #6366f1 0%, #06b6d4 100%)',
      senderAvatarIcon: mainAgent?.avatarIcon || '🤖',
      senderAvatarImage: mainAgent?.avatarImage,
      role: 'agent',
      content: '',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    // Render text bubble immediately so streaming text populates it live
    setMessages(prev => [...prev, agentMsg]);

    const audioQueue: { blobUrl: string }[] = [];
    let isPlayingAudioQueue = false;

    const processAudioQueue = async () => {
      if (isPlayingAudioQueue || audioQueue.length === 0 || isMuted || mainAgent?.voiceEnabled === false) return;
      isPlayingAudioQueue = true;
      const nextChunk = audioQueue.shift()!;
      
      setPlayingMessageId(agentMsgId);
      isAgentSpeakingRef.current = true;
      if (recognitionRef.current) {
        try { recognitionRef.current.abort(); } catch(e) {}
      }

      const audio = new Audio(nextChunk.blobUrl);
      audio.playbackRate = audioSpeed;
      audioRef.current = audio;

      const finishChunk = () => {
        isPlayingAudioQueue = false;
        URL.revokeObjectURL(nextChunk.blobUrl);
        if (audioQueue.length > 0) {
          processAudioQueue();
        } else {
          setPlayingMessageId(null);
          isAgentSpeakingRef.current = false;
          if (isListeningRef.current) {
            setTimeout(() => safeRestartListening(), 300);
          }
        }
      };

      audio.onended = finishChunk;
      audio.onerror = finishChunk;
      try {
        await audio.play();
      } catch(e) {
        finishChunk();
      }
    };

    let accumulatedText = '';
    let updateScheduled = false;

    const flushTextUpdate = () => {
      setMessages(prev => prev.map(m => m.id === agentMsgId ? { ...m, content: accumulatedText } : m));
      updateScheduled = false;
    };

    const pitch = mainAgent?.voiceProfile?.pitch || 1.0;
    const rate = mainAgent?.voiceProfile?.rate || 1.0;

    try {
      // Clear any leftover audio queue from previous messages
      audioQueueRef.current = [];
      isPlayingChunkRef.current = false;

      await streamChat(
        targetAgentId,
        textToSend,
        messages,
        mainAgent?.modelMapping || 'llama-3.2-3b',
        // onToken: stream text live into message bubble at smooth 60fps
        (token: string) => {
          accumulatedText += token;
          if (!updateScheduled) {
            updateScheduled = true;
            requestAnimationFrame(flushTextUpdate);
          }
        },
        // onAudioChunk: play each sentence's audio immediately as it arrives
        (base64: string, text: string, mediaType: string) => {
          if (!isMuted && mainAgent?.voiceEnabled !== false) {
            enqueueAudioChunk(base64, text, mediaType, agentMsgId);
          }
        },
        // onDone: finalize text, audio queue will drain itself
        (fullText?: string) => {
          flushTextUpdate();
          setIsLoading(false);
        },
        // onError
        (err: string) => {
          console.error('Stream error:', err);
          setIsLoading(false);
        }
      );
    } catch (err) {
      console.error('Failed to stream chat:', err);
      setIsLoading(false);
    } finally {
      flushTextUpdate();
      setIsLoading(false);
    }
  };

  const playAudio = async (text: string, pitch = 1.0, rate = 1.0, messageId?: string, targetAgentId?: string) => {
    stopAllVoiceAudio();
    if (messageId) setPlayingMessageId(messageId);
    
    // Explicitly lock speech recognition while agent speaks so Chrome un-mutes the speaker output
    isAgentSpeakingRef.current = true;
    if (recognitionRef.current) {
      try { recognitionRef.current.abort(); } catch(e) {}
    }

    return await playBackendAudioStream(text, pitch, rate, messageId, targetAgentId || selectedAgentId);
  };

  const safeRestartListening = () => {
    if (!isListeningRef.current || isAgentSpeakingRef.current) return;
    try {
      if (recognitionRef.current) {
        recognitionRef.current.start();
      } else {
        initSpeechRecognition(speechLang);
        setTimeout(() => {
          if (isListeningRef.current && !isAgentSpeakingRef.current && recognitionRef.current) {
            try { recognitionRef.current.start(); } catch(e) {}
          }
        }, 150);
      }
    } catch(e) {
      try {
        initSpeechRecognition(speechLang);
        setTimeout(() => {
          if (isListeningRef.current && !isAgentSpeakingRef.current && recognitionRef.current) {
            try { recognitionRef.current.start(); } catch(err) {}
          }
        }, 150);
      } catch(err) {}
    }
  };

  const playBackendAudioStream = async (text: string, pitch: number, rate: number, messageId?: string, targetAgentId?: string): Promise<void> => {
    const agentObj = agents.find(a => a.id === (targetAgentId || selectedAgentId));
    const voiceModel = agentObj?.voiceProfile?.voiceId || agentObj?.voiceProfile?.clonedVoiceBase || undefined;
    const samplePath = agentObj?.voiceProfile?.samplePath || undefined;

    const url = getAudioStreamUrl(text, pitch, rate, targetAgentId || selectedAgentId, samplePath, voiceModel);
    
    try {
      const res = await fetch(url, { headers: getAuthHeaders() });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      if (blob.size === 0) throw new Error('0 bytes audio response');
      
      const blobUrl = URL.createObjectURL(blob);
      const audio = new Audio(blobUrl);
      audio.playbackRate = audioSpeed;
      audioRef.current = audio;

      return new Promise<void>((resolve) => {
        const handleAudioEnd = () => {
          setPlayingMessageId(null);
          isAgentSpeakingRef.current = false;
          URL.revokeObjectURL(blobUrl);
          resolve();

          if (isListeningRef.current) {
            setTimeout(() => {
              safeRestartListening();
            }, 300);
          }
        };

        audio.onended = handleAudioEnd;
        audio.onerror = (e) => {
          console.error('Audio element error:', e);
          handleAudioEnd();
        };

        audio.play().catch(e => {
          console.error('Audio play exception:', e);
          handleAudioEnd();
        });
      });
    } catch (err) {
      console.error('Failed to fetch/play audio stream:', err);
      setPlayingMessageId(null);
      isAgentSpeakingRef.current = false;
    }
  };

  const toggleGroupAgent = (agentId: string) => {
    if (groupSelectedAgentIds.includes(agentId)) {
      if (groupSelectedAgentIds.length > 1) {
        setGroupSelectedAgentIds(groupSelectedAgentIds.filter(id => id !== agentId));
      }
    } else {
      setGroupSelectedAgentIds([...groupSelectedAgentIds, agentId]);
    }
  };

  const activeAgent = agents.find(a => a.id === selectedAgentId) || agents[0];

  return (
    <div className="chat-workspace-grid">
      
      {/* LEFT COLUMN: Mode Switcher & Agent Participant Selector */}
      <div className="glass-panel chat-workspace-sidebar" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
        <div>
          <h3 style={{ fontSize: '15px', color: 'var(--text-muted)', marginBottom: '12px' }}>Chatroom Mode</h3>
          <div style={{ display: 'flex', background: '#f1f5f9', padding: '4px', borderRadius: '10px', border: '1px solid var(--bg-card-border)' }}>
            <button
              onClick={() => setChatMode('single')}
              style={{
                flex: 1,
                padding: '8px',
                borderRadius: '8px',
                fontSize: '12px',
                fontWeight: 600,
                background: chatMode === 'single' ? 'var(--accent-primary)' : 'transparent',
                color: chatMode === 'single' ? '#fff' : 'var(--text-muted)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px'
              }}
            >
              <User size={14} /> 1-on-1 Studio
            </button>
            <button
              onClick={() => setChatMode('group')}
              style={{
                flex: 1,
                padding: '8px',
                borderRadius: '8px',
                fontSize: '12px',
                fontWeight: 600,
                background: chatMode === 'group' ? 'var(--accent-secondary)' : 'transparent',
                color: chatMode === 'group' ? '#fff' : 'var(--text-muted)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px'
              }}
            >
              <Users size={14} /> Multi-Agent Room
            </button>
          </div>
        </div>

        {chatMode === 'single' ? (
          <div>
            <h3 style={{ fontSize: '14px', color: 'var(--text-main)', marginBottom: '12px' }}>Select Agent Partner</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {agents.map((ag) => (
                <div
                  key={ag.id}
                  onClick={() => setSelectedAgentId(ag.id)}
                  style={{
                    padding: '10px 12px',
                    borderRadius: '10px',
                    background: selectedAgentId === ag.id ? 'rgba(79, 70, 229, 0.1)' : '#f8fafc',
                    border: selectedAgentId === ag.id ? '1px solid var(--accent-primary)' : '1px solid var(--bg-card-border)',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px'
                  }}
                >
                  <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: ag.avatar, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden', flexShrink: 0 }}>
                    {ag.avatarImage ? (
                      <img src={ag.avatarImage} alt={ag.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                    ) : (
                      ag.avatarIcon || '🤖'
                    )}
                  </div>
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 600 }}>{ag.name}</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{ag.personaTag}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div>
            <h3 style={{ fontSize: '14px', color: 'var(--text-main)', marginBottom: '12px' }}>Participating Agents</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {agents.map((ag) => {
                const isSelected = groupSelectedAgentIds.includes(ag.id);
                return (
                  <div
                    key={ag.id}
                    onClick={() => toggleGroupAgent(ag.id)}
                    style={{
                      padding: '10px 12px',
                      borderRadius: '10px',
                      background: isSelected ? 'rgba(2, 132, 199, 0.1)' : '#f8fafc',
                      border: isSelected ? '1px solid var(--accent-secondary)' : '1px solid var(--bg-card-border)',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      gap: '10px'
                    }}
                  >
                    <input type="checkbox" checked={isSelected} readOnly />
                    <div style={{ width: '28px', height: '28px', borderRadius: '6px', background: ag.avatar, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '14px', overflow: 'hidden', flexShrink: 0 }}>
                      {ag.avatarImage ? (
                        <img src={ag.avatarImage} alt={ag.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                      ) : (
                        ag.avatarIcon || '🤖'
                      )}
                    </div>
                    <div>
                      <div style={{ fontSize: '12px', fontWeight: 600 }}>{ag.name}</div>
                      <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{ag.role}</div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Audio Output Controls */}
        <div style={{ marginTop: 'auto', background: '#f8fafc', padding: '14px', borderRadius: '12px', border: '1px solid var(--bg-card-border)' }}>
          <div style={{ fontSize: '12px', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '8px' }}>Audio Output Controls</div>
          
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
            <button
              onClick={() => {
                if (playingMessageId) {
                  stopAllVoiceAudio();
                }
                setIsMuted(!isMuted);
              }}
              style={{
                flex: 1,
                background: isMuted ? 'rgba(239, 68, 68, 0.15)' : 'rgba(16, 185, 129, 0.15)',
                color: isMuted ? '#ef4444' : '#10b981',
                border: isMuted ? '1px solid rgba(239, 68, 68, 0.3)' : '1px solid rgba(16, 185, 129, 0.3)',
                padding: '6px 10px',
                borderRadius: '6px',
                fontSize: '11px',
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '4px',
                cursor: 'pointer'
              }}
              title={isMuted ? 'Enable auto voice responses' : 'Mute auto voice responses'}
            >
              {isMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
              {isMuted ? 'Voice Response: OFF' : 'Voice Response: ON'}
            </button>

            <select
              value={audioSpeed}
              onChange={(e) => setAudioSpeed(parseFloat(e.target.value))}
              style={{ padding: '4px 8px', fontSize: '11px' }}
            >
              <option value="0.75">0.75x</option>
              <option value="1.0">1.0x Speed</option>
              <option value="1.25">1.25x</option>
              <option value="1.5">1.5x</option>
            </select>
          </div>
        </div>
      </div>

      {/* RIGHT COLUMN: Chat Feed & Controls */}
      <div className="glass-panel chat-feed-container" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        
        {/* Chatroom Top Banner */}
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--bg-card-border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: '#ffffff' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ width: '40px', height: '40px', borderRadius: '10px', background: activeAgent?.avatar, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '20px', overflow: 'hidden', flexShrink: 0 }}>
              {activeAgent?.avatarImage ? (
                <img src={activeAgent.avatarImage} alt={activeAgent.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              ) : (
                activeAgent?.avatarIcon || '🎙️'
              )}
            </div>
            <div>
              <h3 style={{ fontSize: '16px', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '8px' }}>
                {chatMode === 'single' ? activeAgent?.name : 'Multi-Agent Group Planning Room'}
                <span style={{ fontSize: '11px', color: '#a78bfa', background: 'rgba(139, 92, 246, 0.2)', padding: '2px 8px', borderRadius: '6px', border: '1px solid rgba(139, 92, 246, 0.4)', fontWeight: 600 }}>
                  FROM {activeAgent?.modelMapping || 'llama-3.2-3b'}
                </span>
              </h3>
              <div style={{ fontSize: '12px', color: 'var(--text-muted)', display: 'flex', gap: '10px' }}>
                <span>{chatMode === 'single' ? activeAgent?.role : `${groupSelectedAgentIds.length} Agents Active`}</span>
                <span>•</span>
                <span style={{ color: activeAgent?.voiceProfile?.cloned ? '#f472b6' : 'var(--accent-secondary)' }}>
                  {activeAgent?.voiceProfile?.cloned ? '🧬 Cloned Neural Voice' : '🎙️ System Voice'}
                </span>
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {(() => {
              const activeAg = agents.find(a => a.id === selectedAgentId) || agents[0];
              const curLang = agentLanguageMap[selectedAgentId] || activeAg?.responseLanguage || 'Hinglish';
              const isHindi = curLang === 'Hindi';
              return (
                <select
                  value={curLang}
                  onChange={async (e) => {
                    if (!activeAg) return;
                    const newLang = e.target.value as 'Hindi' | 'Hinglish';
                    setAgentLanguageMap(prev => ({ ...prev, [selectedAgentId]: newLang }));
                    activeAg.responseLanguage = newLang;
                    await updateAgent({ ...activeAg, responseLanguage: newLang });
                    if (onAgentsUpdated) onAgentsUpdated();
                  }}
                  style={{
                    padding: '4px 10px',
                    borderRadius: '10px',
                    fontSize: '12px',
                    fontWeight: 600,
                    background: isHindi ? 'rgba(139, 92, 246, 0.15)' : 'rgba(59, 130, 246, 0.15)',
                    color: isHindi ? '#8b5cf6' : '#2563eb',
                    border: isHindi ? '1px solid rgba(139, 92, 246, 0.4)' : '1px solid rgba(59, 130, 246, 0.4)',
                    cursor: 'pointer'
                  }}
                  title="Select Agent Response Language"
                >
                  <option value="Hinglish">🗣️ Text: Hinglish</option>
                  <option value="Hindi">🇮🇳 Text: देवनागरी हिंदी</option>
                </select>
              );
            })()}

            <button
              onClick={() => setIsMuted(!isMuted)}
              style={{
                background: isMuted ? 'rgba(239, 68, 68, 0.1)' : 'rgba(16, 185, 129, 0.1)',
                color: isMuted ? '#dc2626' : '#059669',
                border: isMuted ? '1px solid rgba(239, 68, 68, 0.3)' : '1px solid rgba(16, 185, 129, 0.3)',
                padding: '4px 10px',
                borderRadius: '10px',
                fontSize: '12px',
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                cursor: 'pointer'
              }}
              title={isMuted ? 'Click to enable voice responses' : 'Click to disable voice responses'}
            >
              {isMuted ? <VolumeX size={14} /> : <Volume2 size={14} />}
              {isMuted ? 'Voice OFF' : 'Voice ON'}
            </button>

            <button
              onClick={handleClearChatHistory}
              style={{
                background: 'rgba(239, 68, 68, 0.1)',
                color: '#dc2626',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                padding: '4px 10px',
                borderRadius: '10px',
                fontSize: '12px',
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: '4px',
                cursor: 'pointer'
              }}
              title="Clear entire chat history"
            >
              <Trash2 size={14} /> Clear Chat
            </button>

            {playingMessageId && (
              <button
                onClick={stopAllVoiceAudio}
                style={{
                  background: 'rgba(239, 68, 68, 0.25)',
                  color: '#f87171',
                  border: '1px solid #f87171',
                  padding: '4px 12px',
                  borderRadius: '12px',
                  fontSize: '12px',
                  fontWeight: 600,
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px'
                }}
              >
                <Square size={14} /> Stop Voice Playback
              </button>
            )}
            <span style={{ fontSize: '11px', color: 'var(--accent-green)', background: 'rgba(16, 185, 129, 0.15)', padding: '4px 10px', borderRadius: '12px', border: '1px solid rgba(16, 185, 129, 0.3)' }}>
              100% Local Model Active
            </span>
          </div>
        </div>

        {/* Chat Feed */}
        <div ref={chatFeedRef} style={{ flex: 1, padding: '24px 20px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '16px', maxWidth: '960px', margin: '0 auto', width: '100%' }}>
          {messages.map((msg) => {
            const isPlayingThis = playingMessageId === msg.id;

            return (
              <div
                key={msg.id}
                style={{
                  display: 'flex',
                  gap: '12px',
                  alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                  maxWidth: '85%'
                }}
              >
                {msg.role !== 'user' && (
                  <div style={{ width: '36px', height: '36px', borderRadius: '10px', background: msg.senderAvatar, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px', flexShrink: 0, overflow: 'hidden' }}>
                    {msg.senderAvatarImage ? (
                      <img src={msg.senderAvatarImage} alt={msg.senderName} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                    ) : (
                      msg.senderAvatarIcon
                    )}
                  </div>
                )}

                <div
                  style={{
                    background: msg.role === 'user'
                      ? 'linear-gradient(135deg, #4f46e5 0%, #6366f1 100%)'
                      : '#f1f5f9',
                    border: msg.role === 'user' ? 'none' : '1px solid var(--bg-card-border)',
                    padding: '14px 18px',
                    borderRadius: '16px',
                    color: msg.role === 'user' ? '#ffffff' : '#0f172a'
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
                    <span style={{ fontSize: '12px', fontWeight: 700, color: msg.role === 'user' ? '#e0e7ff' : 'var(--accent-secondary)' }}>
                      {msg.senderName}
                    </span>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      {msg.role === 'agent' && (
                        <button
                          onClick={() => {
                            if (isPlayingThis) {
                              stopAllVoiceAudio();
                            } else {
                              const senderAgent = agents.find(a => a.id === msg.senderId) || activeAgent;
                              playAudio(
                                msg.content,
                                senderAgent?.voiceProfile?.pitch || 1.0,
                                senderAgent?.voiceProfile?.rate || 1.0,
                                msg.id,
                                senderAgent?.id
                              );
                            }
                          }}
                          style={{
                            background: isPlayingThis ? 'rgba(239, 68, 68, 0.9)' : 'linear-gradient(135deg, #1e293b 0%, #0f172a 100%)',
                            color: '#ffffff',
                            border: '1px solid rgba(15, 23, 42, 0.3)',
                            padding: '4px 10px',
                            borderRadius: '6px',
                            fontSize: '11px',
                            fontWeight: 700,
                            display: 'flex',
                            alignItems: 'center',
                            gap: '4px',
                            cursor: 'pointer',
                            boxShadow: '0 2px 8px rgba(0,0,0,0.15)'
                          }}
                          title={isPlayingThis ? "Stop Voice Playback" : "Listen to Agent Spoken Voice"}
                        >
                          {isPlayingThis ? <Square size={12} /> : <Play size={12} />}
                          {isPlayingThis ? 'Stop Voice' : '🔊 Listen Voice'}
                        </button>
                      )}
                      <span style={{ fontSize: '10px', color: 'rgba(255,255,255,0.5)' }}>
                        {msg.timestamp}
                      </span>
                    </div>
                  </div>

                  <p style={{ fontSize: '14px', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
                    {msg.content}
                  </p>

                  {/* Sub-responses for multi-agent group mode */}
                  {msg.groupResponses && msg.groupResponses.length > 0 && (
                    <div style={{ marginTop: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      {msg.groupResponses.map((g, idx) => (
                        <div key={idx} style={{ background: 'rgba(0,0,0,0.3)', padding: '10px', borderRadius: '8px', borderLeft: '3px solid var(--accent-pink)' }}>
                          <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--accent-pink)', marginBottom: '2px' }}>
                            {g.avatarIcon} {g.agentName}
                          </div>
                          <p style={{ fontSize: '12px', color: '#e2e8f0' }}>{g.text}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })}

          {isLoading && (
            <div style={{ display: 'flex', gap: '10px', alignItems: 'center', color: '#334155', fontSize: '13px', fontWeight: 600, background: '#f1f5f9', padding: '10px 16px', borderRadius: '12px', width: 'fit-content', border: '1px solid var(--bg-card-border)', boxShadow: '0 2px 8px rgba(0,0,0,0.04)' }}>
              <RefreshCw className="recording-pulse" size={16} color="#6366f1" />
              <span>{thinkingMessage}</span>
            </div>
          )}
        </div>

        {/* Audio Frequency Visualizer Canvas */}
        {isHandsFreeListening && (
          <div style={{ height: '40px', background: '#f8fafc', padding: '0 20px', display: 'flex', alignItems: 'center', borderTop: '1px solid var(--bg-card-border)' }}>
            <canvas ref={canvasRef} width={600} height={35} style={{ width: '100%', height: '35px' }} />
          </div>
        )}

        {/* Input Bar & Voice Controls */}
        <div style={{ padding: '16px 20px', borderTop: '1px solid var(--bg-card-border)', background: '#ffffff' }}>
          <div className="chat-input-toolbar" style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
            <button
              onClick={toggleListening}
              style={{
                background: isHandsFreeListening ? 'rgba(239, 68, 68, 0.25)' : 'rgba(139, 92, 246, 0.2)',
                color: isHandsFreeListening ? '#f87171' : 'var(--accent-primary)',
                border: isHandsFreeListening ? '1px solid #f87171' : '1px solid var(--accent-primary)',
                padding: '12px',
                borderRadius: '12px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center'
              }}
              title="Continuous Voice Command Mode"
            >
              {isHandsFreeListening ? <Radio className="recording-pulse" size={20} /> : <Mic size={20} />}
            </button>

            {/* Speech Recognition Language Selector */}
            <select
              value={speechLang}
              onChange={(e) => setSpeechLang(e.target.value)}
              style={{
                background: '#f8fafc',
                color: '#d946ef',
                border: '1px solid var(--accent-pink)',
                borderRadius: '10px',
                padding: '10px 8px',
                fontSize: '12px',
                fontWeight: 700,
                cursor: 'pointer'
              }}
              title="Voice Recognition Language"
            >
              <option value="hi-IN">🇮🇳 Hindi / Hinglish (hi-IN)</option>
              <option value="en-IN">🇮🇳 Indian English (en-IN)</option>
              <option value="en-US">🇺🇸 US English (en-US)</option>
            </select>

            <input
              type="text"
              placeholder={isHandsFreeListening ? 'Listening... Speak your command' : 'Type video prompt or message to agent(s)...'}
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
              style={{ flex: 1, borderRadius: '12px' }}
            />

            <button
              onClick={() => handleSendMessage()}
              style={{
                background: 'linear-gradient(135deg, #8b5cf6 0%, #06b6d4 100%)',
                color: '#fff',
                padding: '0 20px',
                borderRadius: '12px',
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: '8px'
              }}
            >
              <Send size={18} /> Send
            </button>
          </div>
        </div>

      </div>

    </div>
  );
};
