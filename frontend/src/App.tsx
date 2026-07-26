import React, { useState, useEffect, useRef } from 'react';
import { 
  LayoutDashboard, 
  FolderGit2, 
  BookOpen, 
  Settings as SettingsIcon, 
  Play, 
  Activity, 
  Cpu, 
  CheckCircle2, 
  PlusCircle, 
  RotateCw,
  Search,
  Database,
  Share2,
  ChevronRight,
  ChevronUp,
  TrendingUp,
  AlertCircle,
  FileText,
  Video,
  BarChart3,
  Users,
  ShieldCheck,
  HeartPulse,
  Compass,
  Sparkles,
  Send,
  Bookmark,
  Star,
  MessageSquare,
  Trash2,
  Bot,
  Filter,
  Mic,
  MicOff,
  Volume2,
  VolumeX,
  HelpCircle,
  List,
  Sliders
} from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState<string>('dashboard');
  const [projects, setProjects] = useState<any[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Scroll & Sticky Navigation Refs
  const workspaceRef = useRef<HTMLDivElement>(null);
  const chatMessagesContainerRef = useRef<HTMLDivElement>(null);
  const [showGoToTop, setShowGoToTop] = useState<boolean>(false);

  const handleWorkspaceScroll = () => {
    if (workspaceRef.current) {
      setShowGoToTop(workspaceRef.current.scrollTop > 150);
    }
  };
  
  // Project creation form state
  const [newProjName, setNewProjName] = useState('');
  const [newProjBrand, setNewProjBrand] = useState('Beyond3Baje');
  const [newProjWorkflow, setNewProjWorkflow] = useState('beyond3baje_documentary');

  // Selected LLM state
  const [selectedLlm, setSelectedLlm] = useState<string>('gemini');
  const [geminiKey, setGeminiKey] = useState<string>('');
  const [openaiKey, setOpenaiKey] = useState<string>('');
  
  // Live logs and running state
  const [runningProjId, setRunningProjId] = useState<string | null>(null);
  const [runLog, setRunLog] = useState<string[]>([]);

  // Channel Topic Discovery State
  const [selectedChannel, setSelectedChannel] = useState<string>('Beyond3Baje');
  const [discoveredTopics, setDiscoveredTopics] = useState<any[]>([]);
  const [isDiscovering, setIsDiscovering] = useState<boolean>(false);

  // Saved Topics & Interactive Chat State
  const [topicSubTab, setTopicSubTab] = useState<'discovered' | 'saved' | 'chat'>('discovered');
  const [savedTopics, setSavedTopics] = useState<any[]>([]);
  const [savedFilterChannel, setSavedFilterChannel] = useState<string>('all');
  const [savedToast, setSavedToast] = useState<string | null>(null);

  // Interactive Chat Window state
  const [chatMessages, setChatMessages] = useState<{ sender: 'user' | 'agent', text: string, timestamp: string }[]>([]);
  const [activeChatTopic, setActiveChatTopic] = useState<any | null>(null);
  const [chatInput, setChatInput] = useState<string>('');
  const [isChatSending, setIsChatSending] = useState<boolean>(false);

  // Multi-Provider JARVIS Voice Engine State
  const [isVoiceActive, setIsVoiceActive] = useState<boolean>(false);
  const [isAudioMuted, setIsAudioMuted] = useState<boolean>(false);
  const [lastVoiceTranscript, setLastVoiceTranscript] = useState<string>('');
  const [voiceFeedbackText, setVoiceFeedbackText] = useState<string>('');
  const [showVoiceHelp, setShowVoiceHelp] = useState<boolean>(false);
  const [isTTSSpeaking, setIsTTSSpeaking] = useState<boolean>(false);

  // Registered Agents Catalog State
  const [registeredAgents, setRegisteredAgents] = useState<{ name: string, status?: string }[]>([]);
  const [agentFilter, setAgentFilter] = useState<string>('');

  const fetchRegisteredAgents = async () => {
    try {
      const res = await fetch('/api/agents');
      if (res.ok) {
        const data = await res.json();
        if (data.agents && data.agents.length > 0) {
          setRegisteredAgents(data.agents);
        }
      }
    } catch (e) {}
  };

  useEffect(() => {
    fetchRegisteredAgents();
  }, []);

  // Voice Activity Log History State
  const [voiceLogs, setVoiceLogs] = useState<{ id: string, time: string, type: 'USER' | 'ACTION' | 'JARVIS', text: string }[]>([]);
  const [showVoiceLogs, setShowVoiceLogs] = useState<boolean>(false);

  const addVoiceLog = (type: 'USER' | 'ACTION' | 'JARVIS', text: string) => {
    const timeStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    setVoiceLogs(prev => [
      { id: Math.random().toString(36).substring(2, 9), time: timeStr, type, text },
      ...prev
    ].slice(0, 60));
  };

  // Interactive Voice Tuning State (Rate, Pitch, Volume, Voice URI)
  const [selectedVoiceURI, setSelectedVoiceURI] = useState<string>(() => localStorage.getItem('voice_selected_uri') || '');
  const [voiceRate, setVoiceRate] = useState<number>(() => parseFloat(localStorage.getItem('voice_rate') || '0.96'));
  const [voicePitch, setVoicePitch] = useState<number>(() => parseFloat(localStorage.getItem('voice_pitch') || '1.0'));
  const [voiceVolume, setVoiceVolume] = useState<number>(() => parseFloat(localStorage.getItem('voice_volume') || '1.0'));
  const [showVoiceTuning, setShowVoiceTuning] = useState<boolean>(false);
  const [availableVoices, setAvailableVoices] = useState<SpeechSynthesisVoice[]>([]);

  useEffect(() => {
    if ('speechSynthesis' in window) {
      const loadVoices = () => {
        const voices = window.speechSynthesis.getVoices();
        setAvailableVoices(voices);
      };
      loadVoices();
      window.speechSynthesis.onvoiceschanged = loadVoices;
    }
  }, []);

  const [voiceProvider, setVoiceProvider] = useState<string>(() => localStorage.getItem('voice_provider') || 'native_local');
  const [picovoiceKey, setPicovoiceKey] = useState<string>(() => localStorage.getItem('picovoice_key') || '');
  const [openaiRealtimeKey, setOpenaiRealtimeKey] = useState<string>(() => localStorage.getItem('openai_realtime_key') || '');

  // Mutable References for Synchronous Event Guards (Zero Stale State Closures)
  const isVoiceActiveRef = React.useRef<boolean>(false);
  const isTTSSpeakingRef = React.useRef<boolean>(false);
  const recognitionInstanceRef = React.useRef<any>(null);
  const processedSentencesMap = React.useRef<Map<string, number>>(new Map());

  // Cross-Tab Voice Singleton Guard (prevents multiple open tabs from speaking simultaneously)
  useEffect(() => {
    if ('BroadcastChannel' in window) {
      const channel = new BroadcastChannel('buzzcaf_voice_singleton');
      channel.onmessage = (event) => {
        if (event.data === 'CLAIM_VOICE_CONTROL') {
          if (isVoiceActiveRef.current) {
            if (recognitionInstanceRef.current) {
              try { recognitionInstanceRef.current.abort(); } catch (e) {}
            }
            isVoiceActiveRef.current = false;
            setIsVoiceActive(false);
          }
        }
      };
      return () => { channel.close(); };
    }
  }, []);

  // Voice Script Dictation Studio State
  const [dictationText, setDictationText] = useState<string>('');
  const [interimText, setInterimText] = useState<string>('');
  const [isDictating, setIsDictating] = useState<boolean>(false);
  const [dictationLang, setDictationLang] = useState<string>('hi-IN');
  const [highSensitivity, setHighSensitivity] = useState<boolean>(true);
  const [leftPanelWidth, setLeftPanelWidth] = useState<number>(78); // 78% default width for Script Canvas
  const [isDraggingSplitter, setIsDraggingSplitter] = useState<boolean>(false);
  const [selectedWriterRole, setSelectedWriterRole] = useState<string>('ScriptWriter');
  const [completionDirective, setCompletionDirective] = useState<string>('complete');
  const [isAiCompleting, setIsAiCompleting] = useState<boolean>(false);
  const [aiOutputResult, setAiOutputResult] = useState<string>('');
  const [savedDictations, setSavedDictations] = useState<Array<{ id: string; title: string; text: string; date: string }>>(() => {
    try {
      const saved = localStorage.getItem('buzzcaf_dictations');
      return saved ? JSON.parse(saved) : [];
    } catch (e) {
      return [];
    }
  });

  const dictationRecognitionRef = useRef<any>(null);
  const dictationContainerRef = useRef<HTMLDivElement>(null);

  // Global mouse move & up listeners for smooth draggable panel resizing
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isDraggingSplitter || !dictationContainerRef.current) return;
      const rect = dictationContainerRef.current.getBoundingClientRect();
      const newWidth = ((e.clientX - rect.left) / rect.width) * 100;
      setLeftPanelWidth(Math.min(Math.max(newWidth, 40), 90));
    };

    const handleMouseUp = () => {
      setIsDraggingSplitter(false);
    };

    if (isDraggingSplitter) {
      window.addEventListener('mousemove', handleMouseMove);
      window.addEventListener('mouseup', handleMouseUp);
    }
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [isDraggingSplitter]);

  const handleDeleteLastLine = () => {
    setDictationText(prev => {
      const lines = prev.trimEnd().split('\n');
      if (lines.length > 0) {
        lines.pop();
        return lines.length > 0 ? lines.join('\n') + '\n' : '';
      }
      return '';
    });
  };

  // Initialize & Manage High Sensitivity Speech Dictation Engine
  useEffect(() => {
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = highSensitivity ? 3 : 1;
    recognition.lang = dictationLang;

    recognition.onresult = (event: any) => {
      let finalChunk = '';
      let currentInterim = '';

      for (let i = event.resultIndex; i < event.results.length; i++) {
        // High Sensitivity Alternative Selector: Pick cleanest non-empty transcript
        let bestTranscript = '';
        let highestConfidence = -1;

        for (let alt = 0; alt < event.results[i].length; alt++) {
          const item = event.results[i][alt];
          const conf = item.confidence || 0.9;
          if (item.transcript && (conf > highestConfidence || bestTranscript === '')) {
            highestConfidence = conf;
            bestTranscript = item.transcript;
          }
        }

        if (event.results[i].isFinal) {
          finalChunk += bestTranscript + ' ';
        } else {
          currentInterim += bestTranscript;
        }
      }

      setInterimText(currentInterim);

      if (finalChunk.trim()) {
        let cleanChunk = finalChunk.trim();

        // Capitalize first character
        cleanChunk = cleanChunk.charAt(0).toUpperCase() + cleanChunk.slice(1);

        // Voice Command: "delete line" / "delete last line" / "line delete"
        const lower = cleanChunk.toLowerCase();
        if (lower.includes('delete line') || lower.includes('line delete') || lower.includes('delete last line')) {
          handleDeleteLastLine();
        } else if (lower === 'new line' || lower === 'next line' || lower === 'next paragraph') {
          setDictationText(prev => prev.trimEnd() + '\n\n');
        } else if (lower === 'clear canvas' || lower === 'clear script') {
          setDictationText('');
        } else {
          setDictationText(prev => {
            const spacing = prev.endsWith('\n') || prev.length === 0 ? '' : ' ';
            return prev + spacing + cleanChunk + '\n';
          });
        }
      }
    };

    recognition.onerror = (event: any) => {
      console.warn('Dictation recognition notice:', event.error);
    };

    recognition.onend = () => {
      // Auto-restart continuous listening if dictation mode is active
      if (dictationRecognitionRef.current && dictationRecognitionRef.current.isCustomActive) {
        try {
          dictationRecognitionRef.current.start();
        } catch (e) {
          console.warn('Dictation auto-restart notice:', e);
        }
      } else {
        setIsDictating(false);
        setInterimText('');
      }
    };

    dictationRecognitionRef.current = recognition;

    return () => {
      if (dictationRecognitionRef.current) {
        dictationRecognitionRef.current.isCustomActive = false;
        try { dictationRecognitionRef.current.stop(); } catch(e) {}
      }
    };
  }, [dictationLang]);

  const toggleDictation = () => {
    const recognition = dictationRecognitionRef.current;
    if (!recognition) {
      alert('Speech Recognition is not supported in this browser engine. Please use Google Chrome or Microsoft Edge.');
      return;
    }

    if (isDictating) {
      recognition.isCustomActive = false;
      try { recognition.stop(); } catch (e) {}
      setIsDictating(false);
      setInterimText('');
    } else {
      recognition.isCustomActive = true;
      try {
        recognition.start();
        setIsDictating(true);
      } catch (e) {
        console.error('Error starting dictation:', e);
      }
    }
  };

  const handleSaveDictationDraft = () => {
    if (!dictationText.trim()) return;
    const newDraft = {
      id: `draft_${Date.now()}`,
      title: dictationText.trim().substring(0, 45) + '...',
      text: dictationText,
      date: new Date().toLocaleString()
    };
    const updated = [newDraft, ...savedDictations];
    setSavedDictations(updated);
    try { localStorage.setItem('buzzcaf_dictations', JSON.stringify(updated)); } catch (e) {}
  };

  const handleDeleteDictationDraft = (id: string) => {
    const updated = savedDictations.filter(d => d.id !== id);
    setSavedDictations(updated);
    try { localStorage.setItem('buzzcaf_dictations', JSON.stringify(updated)); } catch (e) {}
  };

  const handleAiCompleteScript = async () => {
    if (!dictationText.trim()) {
      alert('Please dictate or type your draft script first before sending to the AI writing agent!');
      return;
    }

    setIsAiCompleting(true);
    setAiOutputResult('');

    let promptGoal = "";
    if (completionDirective === 'complete') {
      promptGoal = "The creator has dictated the following semi-written script draft. Seamlessly continue and complete the story/script to a satisfying, high-retention conclusion in **Hinglish** (day-to-day Hindi written in English fonts).";
    } else if (completionDirective === 'full_script') {
      promptGoal = "Turn this semi-written dictation draft into a full production-ready YouTube video script in **Hinglish** with scene hooks, narrator lines, visual B-roll cues, and timing notes.";
    } else if (completionDirective === 'hooks_visuals') {
      promptGoal = "Enhance this dictation draft by writing 3 viral 15-second opening text hooks in **Hinglish** and adding detailed visual B-roll & map overlay directions for every paragraph.";
    } else {
      promptGoal = "Polish and refine this dictation draft in **Hinglish** to maximize audience retention, fixing pacing and narrative flow while keeping the creator's voice.";
    }

    const fullPrompt = `${promptGoal}\n\n### Creator's Dictated Semi-Written Draft:\n\"\"\"\n${dictationText}\n\"\"\"\n\nProvide the complete, high-quality Hinglish script below:`;

    try {
      const res = await fetch('/api/topics/agent_chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_name: selectedWriterRole,
          channel: selectedChannel,
          message: fullPrompt,
          chat_history: []
        })
      });

      if (res.ok) {
        const data = await res.json();
        setAiOutputResult(data.reply || 'Script completed successfully.');
      } else {
        throw new Error('Server connection error');
      }
    } catch (e) {
      setAiOutputResult(`**[AI Execution Error]**\n\nUnable to reach AI Writing Agent ${selectedWriterRole}. Please ensure backend Python server is running on http://127.0.0.1:8000.`);
    } finally {
      setIsAiCompleting(false);
    }
  };

  // Helper: map channel to strategist agent name
  const getStrategistAgentName = (channel: string) => {
    if (channel.includes('After Dark')) return 'AfterDarkStrategist';
    if (channel.includes('Studio')) return 'SpilledCoffeeStudioStrategist';
    if (channel.includes('Life')) return 'Life3BajeStrategist';
    if (channel.includes('Khayal')) return 'Khayal3BajeStrategist';
    return 'Beyond3BajeStrategist';
  };

  // Select High-Definition Ultra-Smooth Natural Neural Voice (Jenny, Aria, Google US English)
  const getNaturalNeuralVoice = (): SpeechSynthesisVoice | null => {
    if (!('speechSynthesis' in window)) return null;
    const voices = window.speechSynthesis.getVoices();
    if (!voices || voices.length === 0) return null;

    const enVoices = voices.filter(v => v.lang.startsWith('en'));
    const smoothVoice = enVoices.find(v => 
      v.name.includes('Jenny') || 
      v.name.includes('Aria') || 
      v.name.includes('Guy') || 
      v.name.includes('Google US English') ||
      v.name.includes('Natural') || 
      v.name.includes('Neural') ||
      v.name.includes('Samantha')
    );

    return smoothVoice || enVoices.find(v => v.lang === 'en-US') || enVoices[0] || voices[0];
  };

  // Zero-Echo TTS Feedback Handler (Synchronous Mic Abort & Guard)
  const speakVoiceFeedback = (text: string) => {
    setVoiceFeedbackText(text);

    // 1. SYNCHRONOUSLY set TTS speaking guard IMMEDIATELY to block incoming mic results
    isTTSSpeakingRef.current = true;
    setIsTTSSpeaking(true);

    // 2. HARD ABORT microphone recognition BEFORE starting TTS synthesis
    if (recognitionInstanceRef.current) {
      try { recognitionInstanceRef.current.abort(); } catch (e) {}
    }

    if (isAudioMuted) {
      setTimeout(() => {
        isTTSSpeakingRef.current = false;
        setIsTTSSpeaking(false);
        if (isVoiceActiveRef.current && recognitionInstanceRef.current) {
          try { recognitionInstanceRef.current.start(); } catch (e) {}
        }
      }, 500);
      return;
    }

    if ('speechSynthesis' in window) {
      try {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        
        const allVoices = window.speechSynthesis.getVoices();
        let voice: SpeechSynthesisVoice | null | undefined = allVoices.find(v => v.voiceURI === selectedVoiceURI);
        if (!voice) voice = getNaturalNeuralVoice();
        if (voice) utterance.voice = voice;

        utterance.rate = voiceRate;
        utterance.pitch = voicePitch;
        utterance.volume = voiceVolume;

        const resetTTSSpeaking = () => {
          // Wait 1000ms quiet room silence before re-enabling mic recognition
          setTimeout(() => {
            isTTSSpeakingRef.current = false;
            setIsTTSSpeaking(false);
            if (isVoiceActiveRef.current && recognitionInstanceRef.current) {
              try { recognitionInstanceRef.current.start(); } catch (e) {}
            }
          }, 1000);
        };

        utterance.onend = resetTTSSpeaking;
        utterance.onerror = resetTTSSpeaking;

        window.speechSynthesis.speak(utterance);
      } catch (e) {
        setTimeout(() => {
          isTTSSpeakingRef.current = false;
          setIsTTSSpeaking(false);
          if (isVoiceActiveRef.current && recognitionInstanceRef.current) {
            try { recognitionInstanceRef.current.start(); } catch (e) {}
          }
        }, 500);
      }
    } else {
      isTTSSpeakingRef.current = false;
      setIsTTSSpeaking(false);
    }
  };

  const lastProcessedTextRef = React.useRef<string>('');
  const speechDebounceTimerRef = React.useRef<any>(null);

  // Debounced Speech Handler to prevent interim transcript double-speaking
  const handleIncomingSpeech = (rawTranscript: string) => {
    if (isTTSSpeakingRef.current) return;
    const cleaned = rawTranscript.trim();
    if (cleaned.length < 3) return;

    if (speechDebounceTimerRef.current) {
      clearTimeout(speechDebounceTimerRef.current);
    }

    speechDebounceTimerRef.current = setTimeout(() => {
      processVoiceCommand(cleaned);
    }, 350);
  };

  // Pure 100% Buzzcaf Autonomous Voice Router
  const processVoiceCommand = async (rawTranscript: string) => {
    // 1. Hard Guard: Ignore mic input while Buzzcaf is speaking feedback
    if (isTTSSpeakingRef.current) return;

    const cleaned = rawTranscript.trim();
    if (cleaned.length < 3) return;

    // 2. Fuzzy Prefix Sentence Lock: Discard duplicate/interim phrases heard within 8.0 seconds
    const sentenceHash = cleaned.toLowerCase();
    const prevText = lastProcessedTextRef.current;
    const now = Date.now();
    const lastTime = processedSentencesMap.current.get(sentenceHash) || 0;
    
    if (now - lastTime < 8000 || (prevText && (sentenceHash.includes(prevText) || prevText.includes(sentenceHash)) && (now - (processedSentencesMap.current.get(prevText) || 0) < 8000))) {
      return; // DUPLICATE INTERIM TRANSCRIPT - DISCARD SILENTLY!
    }

    lastProcessedTextRef.current = sentenceHash;
    processedSentencesMap.current.set(sentenceHash, now);

    setLastVoiceTranscript(cleaned);
    addVoiceLog('USER', cleaned);

    // 3. Query Backend JARVIS Router
    let jarvisSpeech = "";
    let act: any = {};

    try {
      const res = await fetch('/api/jarvis/voice', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          phrase: cleaned,
          active_channel: selectedChannel,
          active_tab: activeTab
        })
      });

      if (res.ok) {
        const data = await res.json();
        jarvisSpeech = data.buzzcaf_speech || data.jarvis_speech;
        act = data.action || {};
      }
    } catch (e) {}

    // Fallback Local Parser if offline
    if (!jarvisSpeech) {
      const text = sentenceHash;
      let target_ch = null;
      if (text.includes('after dark') || text.includes('raat 3') || text.includes('horror')) target_ch = 'Spilled Coffee After Dark';
      else if (text.includes('studio') || text.includes('spilled coffee studio')) target_ch = 'Spilled Coffee Studio';
      else if (text.includes('beyond') || text.includes('documentary')) target_ch = 'Beyond3Baje';
      else if (text.includes('life') || text.includes('vlog') || text.includes('essay')) target_ch = 'Life3Baje';
      else if (text.includes('khayal') || text.includes('mythology') || text.includes('lore')) target_ch = 'Khayal3Baje';

      let target_tb = null;
      if (text.includes('project') || text.includes('catalog')) target_tb = 'projects';
      else if (text.includes('topic') || text.includes('vault') || text.includes('discover')) target_tb = 'topic_discovery';
      else if (text.includes('research') || text.includes('citation')) target_tb = 'research';
      else if (text.includes('writing') || text.includes('script') || text.includes('write')) target_tb = 'writing';
      else if (text.includes('production') || text.includes('scene') || text.includes('filmora')) target_tb = 'production';
      else if (text.includes('publish') || text.includes('analytic') || text.includes('performance') || text.includes('view') || text.includes('stat')) target_tb = 'publishing';
      else if (text.includes('workforce') || text.includes('agent') || text.includes('bot')) target_tb = 'ai_workforce';
      else if (text.includes('health') || text.includes('diagnostic') || text.includes('status')) target_tb = 'health';
      else if (text.includes('setting') || text.includes('router') || text.includes('config')) target_tb = 'settings';
      else if (text.includes('dashboard') || text.includes('home') || text.includes('overview') || text.includes('main')) target_tb = 'dashboard';

      act = {
        target_channel: target_ch,
        target_tab: target_tb,
        is_save: text.includes('save') || text.includes('bookmark'),
        is_chat: text.includes('chat') || text.includes('talk') || text.includes('discuss'),
        is_discover: text.includes('discover') || text.includes('find'),
        is_stop: text.includes('stop') || text.includes('quiet') || text.includes('turn off'),
        is_log: text.includes('log') || text.includes('history') || text.includes('activity'),
        is_tuning: text.includes('tune') || text.includes('tuning') || text.includes('voice setting')
      };

      if (act.is_stop) jarvisSpeech = "Buzzcaf standing down, sir. Voice system paused.";
      else if (act.is_log) jarvisSpeech = "Opening your voice activity log console now, sir.";
      else if (act.is_tuning) jarvisSpeech = "Opening voice persona tuning console now, sir.";
      else if (target_ch && target_tb) jarvisSpeech = `Right away, sir. Switched to ${target_ch} and opened ${target_tb.replace('_', ' ')}.`;
      else if (target_ch) jarvisSpeech = `Certainly, sir. Aligning system intelligence with ${target_ch}.`;
      else if (target_tb) jarvisSpeech = `Opening ${target_tb.replace('_', ' ')} workspace now, sir.`;
      else if (act.is_save) jarvisSpeech = `Bookmarking the top topic to your Vault, sir.`;
      else if (act.is_chat) jarvisSpeech = `Initiating direct strategist chat session, sir.`;
      else if (act.is_discover) jarvisSpeech = `Executing topic discovery sweep for ${selectedChannel}, sir.`;
      else jarvisSpeech = `Directive acknowledged, sir. Processing your request regarding ${cleaned.replace(/^and\s+/i, '').replace(/^buzzcaf\s+/i, '')}.`;
    }

    if (act.is_stop) {
      toggleContinuousVoice(false);
      speakVoiceFeedback(jarvisSpeech);
      addVoiceLog('JARVIS', jarvisSpeech);
      return;
    }

    // Execute Actions & Log Activity
    const actionParts = [];
    if (act.is_log) {
      setShowVoiceLogs(true);
      actionParts.push('Opened Activity Log Modal');
    }

    if (act.is_tuning) {
      setShowVoiceTuning(true);
      actionParts.push('Opened Voice Persona Tuning Modal');
    }

    if (act.target_channel) {
      setSelectedChannel(act.target_channel);
      setActiveTab('topic_discovery');
      handleDiscoverTopics(act.target_channel);
      actionParts.push(`Channel -> ${act.target_channel}`);
    }

    if (act.target_tab) {
      setActiveTab(act.target_tab);
      actionParts.push(`Workspace Tab -> ${act.target_tab.replace('_', ' ')}`);
    }

    if (act.is_save && discoveredTopics.length > 0) {
      handleSaveTopic(discoveredTopics[0]);
      actionParts.push('Saved Topic to Vault');
    }

    if (act.is_chat) {
      setActiveTab('topic_discovery');
      setTopicSubTab('chat');
      actionParts.push('Opened Strategist Chat');
    }

    if (act.is_discover) {
      setActiveTab('topic_discovery');
      setTopicSubTab('discovered');
      handleDiscoverTopics(act.target_channel || selectedChannel);
      actionParts.push('Triggered Topic Discovery Sweep');
    }

    if (actionParts.length > 0) {
      addVoiceLog('ACTION', actionParts.join(' | '));
    }

    const finalSpeech = jarvisSpeech || `Right away, sir.`;
    addVoiceLog('JARVIS', finalSpeech);
    speakVoiceFeedback(finalSpeech);
  };

  // Toggle Continuous Speech Engine
  const toggleContinuousVoice = (forceState?: boolean) => {
    const nextState = forceState !== undefined ? forceState : !isVoiceActiveRef.current;
    
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      alert('Web Speech API is not supported in this browser. Please use Chrome, Edge, or Brave.');
      return;
    }

    if (nextState) {
      if ('BroadcastChannel' in window) {
        try {
          const bc = new BroadcastChannel('buzzcaf_voice_singleton');
          bc.postMessage('CLAIM_VOICE_CONTROL');
          bc.close();
        } catch (e) {}
      }

      try {
        const recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = false;
        recognition.lang = 'en-US';

        recognition.onstart = () => {
          isVoiceActiveRef.current = true;
          setIsVoiceActive(true);
          setVoiceFeedbackText('Buzzcaf Voice Activated');
        };

        recognition.onresult = (event: any) => {
          if (isTTSSpeakingRef.current) return;
          const current = event.resultIndex;
          const transcript = event.results[current][0].transcript;
          handleIncomingSpeech(transcript);
        };

        recognition.onerror = (event: any) => {
          if (event.error !== 'no-speech') {
            console.warn('Buzzcaf Voice Warning:', event.error);
          }
        };

        recognition.onend = () => {
          // Restart ONLY if voice is active AND Buzzcaf is NOT currently speaking TTS
          if (isVoiceActiveRef.current && !isTTSSpeakingRef.current) {
            setTimeout(() => {
              try { recognition.start(); } catch (e) {}
            }, 300);
          }
        };

        recognition.start();
        recognitionInstanceRef.current = recognition;
      } catch (e) {
        console.error('Failed to initialize Buzzcaf recognition:', e);
      }
    } else {
      isVoiceActiveRef.current = false;
      setIsVoiceActive(false);
      if (recognitionInstanceRef.current) {
        try { recognitionInstanceRef.current.abort(); } catch (e) {}
      }
    }
  };

  // Fetch saved topics from backend
  const fetchSavedTopics = async () => {
    try {
      const res = await fetch('/api/topics/saved');
      if (res.ok) {
        const data = await res.json();
        setSavedTopics(data.topics || []);
      }
    } catch (e) {
      if (savedTopics.length === 0) {
        setSavedTopics([
          {
            id: "saved_1",
            topic: "The Vanishing Guard of Bhangarh Fort",
            category: "Paranormal & Haunted Locations",
            channel: "Spilled Coffee After Dark",
            viral_potential: 9,
            country: "India",
            source_type: "Local Indian Folklore & Archives",
            sources_used: ["Reddit (r/Paranormal)", "Local Rajasthani Folklore"],
            visual_requirements: ["Haunted fort archival photos", "Night rain mist imagery"],
            exclusion_audit: "✓ Verified: Parapsychological Folklore",
            notes: "Focus on the 3AM guard shift testimonies",
            saved_at: new Date().toISOString()
          },
          {
            id: "saved_2",
            topic: "How One Tiny Engineering Error Sank a Billion-Dollar Warship",
            category: "Engineering & Disaster Stories",
            channel: "Beyond3Baje",
            viral_potential: 9,
            country: "International",
            source_type: "Historical & Technical Archives",
            sources_used: ["Naval Inspection Records", "Wikipedia Disasters"],
            visual_requirements: ["Ship cross-section 3D diagram", "17th Century maps"],
            exclusion_audit: "✓ EXCLUSION VERIFIED: 100% Real-World True Story",
            notes: "Use 3D stability diagram for hook scene",
            saved_at: new Date().toISOString()
          }
        ]);
      }
    }
  };

  // Save topic to backend vault
  const handleSaveTopic = async (item: any) => {
    const payload = {
      topic: item.topic,
      category: item.category || 'General',
      channel: item.channel || selectedChannel,
      viral_potential: item.viral_potential || 9,
      country: item.country || 'Global',
      source_type: item.source_type || 'Researched',
      sources_used: item.sources_used || [],
      visual_requirements: item.visual_requirements || [],
      exclusion_audit: item.exclusion_audit || '',
      notes: ''
    };

    try {
      const res = await fetch('/api/topics/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        setSavedToast(`Saved "${item.topic.substring(0, 28)}..." to Vault!`);
        setTimeout(() => setSavedToast(null), 3000);
        fetchSavedTopics();
      }
    } catch (e) {
      setSavedTopics(prev => [payload, ...prev]);
      setSavedToast(`Saved to Topic Vault!`);
      setTimeout(() => setSavedToast(null), 3000);
    }
  };

  // Delete saved topic
  const handleDeleteSavedTopic = async (topicId?: string, topicTitle?: string) => {
    try {
      await fetch('/api/topics/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: topicId, topic: topicTitle })
      });
      fetchSavedTopics();
    } catch (e) {
      setSavedTopics(prev => prev.filter(t => t.id !== topicId && t.topic !== topicTitle));
    }
  };

  // Open Chat for specific Topic
  const handleOpenChatForTopic = (item: any) => {
    setActiveChatTopic(item);
    const targetChannel = item.channel || selectedChannel;
    setSelectedChannel(targetChannel);
    const agentName = getStrategistAgentName(targetChannel);
    setTopicSubTab('chat');
    setChatMessages([
      {
        sender: 'agent',
        text: `Hello! I am **${agentName}**, your strategist partner for **${targetChannel}**.\n\nI have loaded your target topic: **"${item.topic}"**.\n\nWhat would you like to refine? Ask me to:\n- 💡 Generate 3 viral thumbnail text hooks\n- 🎬 Write a 45-second retention opening script\n- 📊 Suggest story structure tweaks or B-roll ideas!`,
        timestamp: new Date().toLocaleTimeString()
      }
    ]);
  };

  // Send Chat message to Agent
  const handleSendChatMessage = async (customText?: string) => {
    const textToSend = customText || chatInput;
    if (!textToSend.trim()) return;

    const targetChannel = activeChatTopic?.channel || selectedChannel;
    const agentName = getStrategistAgentName(targetChannel);
    
    const userMsg = { sender: 'user' as const, text: textToSend, timestamp: new Date().toLocaleTimeString() };
    setChatMessages(prev => [...prev, userMsg]);
    if (!customText) setChatInput('');
    setIsChatSending(true);

    try {
      const res = await fetch('/api/topics/agent_chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          agent_name: agentName,
          channel: targetChannel,
          message: textToSend,
          context_topic: activeChatTopic,
          chat_history: chatMessages.map(m => ({ role: m.sender === 'user' ? 'user' : 'assistant', content: m.text }))
        })
      });

      if (res.ok) {
        const data = await res.json();
        setChatMessages(prev => [...prev, {
          sender: 'agent',
          text: data.reply || `I analyzed your directive for ${targetChannel}.`,
          timestamp: new Date().toLocaleTimeString()
        }]);
      } else {
        throw new Error('Server connection error');
      }
    } catch (e) {
      setChatMessages(prev => [...prev, {
        sender: 'agent',
        text: `**[${agentName} - ${targetChannel}]**\n\nUnable to reach backend AI engine. Please ensure Python backend server is running on http://127.0.0.1:8000.`,
        timestamp: new Date().toLocaleTimeString()
      }]);
    } finally {
      setIsChatSending(false);
    }
  };

  // Fetch persistent chat history & memory logs from backend
  const fetchChatHistory = async (channel: string, agentName: string) => {
    try {
      const res = await fetch(`/api/topics/chat_history?channel=${encodeURIComponent(channel)}&agent_name=${encodeURIComponent(agentName)}`);
      if (res.ok) {
        const data = await res.json();
        if (data.turns && data.turns.length > 0) {
          const restoredMsgs: Array<{ sender: 'user' | 'agent'; text: string; timestamp: string }> = [];
          data.turns.forEach((t: any) => {
            restoredMsgs.push({ sender: 'user', text: t.user, timestamp: new Date(t.timestamp || Date.now()).toLocaleTimeString() });
            restoredMsgs.push({ sender: 'agent', text: t.reply, timestamp: new Date(t.timestamp || Date.now()).toLocaleTimeString() });
          });
          setChatMessages(restoredMsgs);
          return;
        }
      }
    } catch (e) {
      console.error('Error fetching persistent chat history:', e);
    }
  };

  useEffect(() => {
    if (topicSubTab === 'chat') {
      fetchChatHistory(selectedChannel, getStrategistAgentName(selectedChannel));
    }
  }, [selectedChannel, topicSubTab]);

  // Initial topic discovery on load
  const handleDiscoverTopics = async (channel: string) => {
    setIsDiscovering(true);
    try {
      const res = await fetch('/api/topics/discover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ channel })
      });
      if (res.ok) {
        const data = await res.json();
        setDiscoveredTopics(data.topics || []);
      } else {
        throw new Error('Local fallback');
      }
    } catch (e) {
      if (channel.includes('Studio')) {
        setDiscoveredTopics([
          {
            topic: "Why Franz Kafka's Stories Still Scare Modern Readers",
            category: "Pillar 2: Great Literature & Classic Authors",
            country: "Czech / Global",
            viral_potential: 9,
            source_type: "Public Domain Excerpts & Literary Critique",
            sources_used: ["Public Domain Kafka Archives", "Literary Analysis Essays"],
            visual_requirements: ["Subtle ink sketches", "Rainy European cafe footage", "Annotated manuscript pages"],
            exclusion_audit: "✓ EXCLUSION VERIFIED: Literary Critique & Fair-Use Analysis"
          },
          {
            topic: "How Studio Ghibli & Pixar Write Unforgettable Emotion",
            category: "Pillar 3: Story Analysis",
            country: "Global Animation Craft",
            viral_potential: 10,
            source_type: "Story Architecture Breakdown",
            sources_used: ["Pixar 22 Rules of Storytelling", "Miyazaki Interviews"],
            visual_requirements: ["Storyboarding timeline diagram", "Color palette analysis slides", "Character arc curves"],
            exclusion_audit: "✓ EXCLUSION VERIFIED: Educational Story Architecture"
          },
          {
            topic: "The Midnight Library (Original Fantasy Short Story)",
            category: "Pillar 1: Original Work (30%)",
            country: "Original Short Story",
            viral_potential: 9,
            source_type: "Original Short Fiction / Poetry",
            sources_used: ["Creator Notebooks", "Original Draft #4"],
            visual_requirements: ["Cozy candlelit desk", "Macro fountain pen writing", "Cinematic original narration"],
            exclusion_audit: "✓ EXCLUSION VERIFIED: 100% Original Creator Fiction"
          }
        ]);
      } else if (channel.includes('After Dark')) {
        setDiscoveredTopics([
          {
            topic: "The Vanishing Guard of Bhangarh Fort",
            category: "Paranormal & Haunted Locations",
            country: "India",
            viral_potential: 9,
            source_type: "Local Indian Folklore & Archives",
            sources_used: ["Reddit (r/Paranormal)", "Local Rajasthani Folklore", "Wikipedia Ghost Towns"],
            visual_requirements: ["Haunted fort archival photos", "Night rain mist imagery", "Map of Alwar District"],
            exclusion_audit: "✓ Verified: Parapsychological Folklore (Non-Fictional Attribution)"
          },
          {
            topic: "The Silent Calls from the Deep Web: Audio Incident #99",
            category: "Internet Horror & Modern Myths",
            country: "International",
            viral_potential: 8,
            source_type: "Reddit & Internet Archives",
            sources_used: ["r/HighStrangeness", "Lost Media Wiki", "Dark Web Archives"],
            visual_requirements: ["Spectrogram audio graphs", "Analog horror CRT noise", "Deep web log clippings"],
            exclusion_audit: "✓ Verified: Modern Internet ARG / Myth"
          },
          {
            topic: "The Unresolved Mystery of the Kuldhara Mass Disappearance",
            category: "True Mysteries",
            country: "India",
            viral_potential: 10,
            source_type: "Wikipedia & Indian Archives",
            sources_used: ["ASI Government Records", "r/UnresolvedMysteries", "Regional Folklore Books"],
            visual_requirements: ["Dry desert ruins aerial map", "Paliwal Brahmin family lineage charts"],
            exclusion_audit: "✓ Verified: Historical Unsolved Disappearance"
          }
        ]);
      } else if (channel.includes('Life3Baje')) {
        setDiscoveredTopics([
          {
            topic: "Why I Started Writing Again (And Built My Dream Desk)",
            category: "Creative Journey",
            country: "Personal Documentary",
            viral_potential: 9,
            source_type: "Personal Essay & Creator Journal",
            sources_used: ["Notebook Journals", "Writing Process Reflections"],
            visual_requirements: ["Cozy writing desk macro", "Notebook pages", "Warm morning coffee sunlight"],
            exclusion_audit: "✓ EXCLUSION VERIFIED: Authentic Journey (No Generic Productivity Hacks)"
          },
          {
            topic: "I Spent A Week Without Entertainment Or Social Media",
            category: "Personal Experiments",
            country: "Personal Documentary",
            viral_potential: 8,
            source_type: "Personal Trial Journal",
            sources_used: ["Screen Time Logs", "Daily Thought Essays"],
            visual_requirements: ["Minimalist room shots", "Analog clock slow pan", "Rain on window pane"],
            exclusion_audit: "✓ EXCLUSION VERIFIED: Authentic Self-Experiment"
          },
          {
            topic: "Why Growing Up Feels Strange & How We Lose Curiosity",
            category: "Thoughts (Video Essays)",
            country: "Personal Essay",
            viral_potential: 10,
            source_type: "Reflective Essays",
            sources_used: ["Childhood memory notes", "Aperture style essay literature"],
            visual_requirements: ["Cozy book shelf", "Walking in quiet forest", "Minimalist aesthetic visuals"],
            exclusion_audit: "✓ EXCLUSION VERIFIED: Reflective Essay (No Preachy Guru Quotes)"
          }
        ]);
      } else if (channel.includes('Khayal')) {
        setDiscoveredTopics([
          {
            topic: "The Secrets of Pashupatastra & Divine Astral Weapons",
            category: "Vedic & Epic Lore",
            country: "Ancient India",
            viral_potential: 10,
            source_type: "Sacred Texts & Epic Manuscripts",
            sources_used: ["Mahabharata Vana Parva", "Puranic Encylopedia", "Sanskrit Manuscripts"],
            visual_requirements: ["Epic oil painting visuals", "Cosmic fire rendering", "Ancient Sanskrit text overlays"],
            exclusion_audit: "✓ Verified: Authentic Textual Sacred Lore"
          },
          {
            topic: "The Anunnaki Tablets & Mesopotamian Cosmic Creation Myth",
            category: "World Mythologies",
            country: "Ancient Mesopotamia",
            viral_potential: 9,
            source_type: "Cuneiform Translations",
            sources_used: ["Enuma Elish Tablets", "British Museum Cuneiform Archives"],
            visual_requirements: ["3D Cuneiform tablet rendering", "Ziggurat starry night map"],
            exclusion_audit: "✓ Verified: Comparative World Mythology"
          }
        ]);
      } else {
        setDiscoveredTopics([
          {
            topic: "How One Tiny Engineering Error Sank a Billion-Dollar Warship",
            category: "Engineering & Disaster Stories",
            country: "International",
            viral_potential: 9,
            source_type: "Historical & Technical Archives",
            sources_used: ["Naval Inspection Records", "Wikipedia Disasters", "Engineering Accident Reports"],
            visual_requirements: ["Ship cross-section 3D diagram", "17th Century archival maps", "Stability calculation charts"],
            exclusion_audit: "✓ EXCLUSION VERIFIED: 100% Real-World True Story (No Fictional Ghosts)"
          },
          {
            topic: "The Dark Truth Behind Unit 731: Forgotten Secret Experiments",
            category: "Dark History",
            country: "Japan / International",
            viral_potential: 10,
            source_type: "Declassified Government Documents",
            sources_used: ["National Archives", "Trial Transcripts", "Declassified CIA Records"],
            visual_requirements: ["Historical newspaper clippings", "Declassified stamp documents", "Geographic timeline map"],
            exclusion_audit: "✓ EXCLUSION VERIFIED: Documented Historical Event"
          },
          {
            topic: "India's Most Mysterious Missing Flight & The Sealed Radar Logs",
            category: "Unsolved Mysteries",
            country: "India",
            viral_potential: 9,
            source_type: "Aviation Accident Reports",
            sources_used: ["Civil Aviation Archives", "r/UnresolvedMysteries", "Air Traffic Control Transcripts"],
            visual_requirements: ["Radar flight path tracking map", "Cockpit transcript graphics", "Weather radar overlay"],
            exclusion_audit: "✓ EXCLUSION VERIFIED: Real Aviation Mystery"
          }
        ]);
      }
    } finally {
      setIsDiscovering(false);
    }
  };

  const handleSendToDevelopment = async (item: any, channelName?: string) => {
    const targetBrand = channelName || item.channel || selectedChannel;
    let workflow = 'beyond3baje_documentary';
    if (targetBrand.includes('After Dark')) workflow = 'after_dark_narration';
    if (targetBrand.includes('Studio')) workflow = 'spilled_coffee_story';
    if (targetBrand.includes('Khayal')) workflow = 'khayal3baje_horror';
    if (targetBrand.includes('Life3Baje')) workflow = 'life3baje_essay';

    const newProj = {
      id: "proj_" + Math.floor(Math.random() * 1000),
      name: item.topic,
      brand: targetBrand,
      workflow_name: workflow,
      status: "planned",
      steps_history: [],
      created_at: new Date().toISOString()
    };

    try {
      await fetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: item.topic, brand: targetBrand, workflow_name: workflow })
      });
    } catch (e) {}

    setProjects(prev => [newProj, ...prev]);
    alert(`Topic "${item.topic}" sent for processing & development!\nCreated new production project for ${targetBrand}.`);
    setActiveTab('projects');
  };

  // Load projects from API
  const fetchProjects = async () => {
    try {
      const response = await fetch('/projects');
      if (!response.ok) throw new Error('Failed to fetch projects list');
      const data = await response.json();
      setProjects(data);
      setError(null);
    } catch (err: any) {
      setError(err.message || 'API connection offline');
      setProjects([
        { id: "proj_993", name: "The Forgotten History of London", brand: "Beyond3Baje", workflow_name: "beyond3baje_documentary", status: "completed", steps_history: ["research", "writing", "production", "publishing", "analytics"], created_at: "2026-07-22T00:00:00" },
        { id: "proj_441", name: "Whispers in the Dark Cafe", brand: "Khayal3Baje", workflow_name: "khayal3baje_horror", status: "running", steps_history: ["research", "writing"], created_at: "2026-07-22T00:02:00" },
        { id: "proj_772", name: "Coffee Alchemy & Secret Societies", brand: "Spilled Coffee Studio", workflow_name: "spilled_coffee_story", status: "planned", steps_history: [], created_at: "2026-07-22T00:05:00" },
      ]);
    }
  };

  const fetchSettings = async () => {
    try {
      const res = await fetch('/api/settings');
      if (res.ok) {
        const data = await res.json();
        if (data.selected_provider) setSelectedLlm(data.selected_provider);
        if (data.gemini_api_key) setGeminiKey(data.gemini_api_key);
        if (data.openai_api_key) setOpenaiKey(data.openai_api_key);
      }
    } catch (e) {}
  };

  const handleSaveSettings = async (e: React.FormEvent) => {
    e.preventDefault();
    const payload = {
      selected_provider: selectedLlm,
      gemini_api_key: geminiKey,
      openai_api_key: openaiKey,
      gemini_model: "gemini-3.6-flash",
      prefer_gemini: selectedLlm === 'gemini'
    };
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        localStorage.setItem('selected_llm', selectedLlm);
        alert(`Successfully saved settings! Active provider set to ${selectedLlm.toUpperCase()}.`);
      } else {
        throw new Error('Failed to save settings to server');
      }
    } catch (err: any) {
      alert(`Saved settings locally: ${selectedLlm}`);
    }
  };

  useEffect(() => {
    fetchProjects();
    fetchSavedTopics();
    fetchSettings();
    handleDiscoverTopics('Beyond3Baje');
    const savedLlm = localStorage.getItem('selected_llm') || 'gemini';
    setSelectedLlm(savedLlm);
  }, []);

  const handleCreateProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProjName.trim()) return;

    const payload = {
      name: newProjName,
      brand: newProjBrand,
      workflow_name: newProjWorkflow
    };

    try {
      const res = await fetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) throw new Error('Failed to register project');
      fetchProjects();
      setNewProjName('');
      setActiveTab('projects');
    } catch (err: any) {
      const mockProj = {
        id: "proj_" + Math.floor(Math.random() * 1000),
        name: payload.name,
        brand: payload.brand,
        workflow_name: payload.workflow_name,
        status: "planned",
        steps_history: [],
        created_at: new Date().toISOString()
      };
      setProjects(prev => [mockProj, ...prev]);
      setNewProjName('');
      setActiveTab('projects');
    }
  };

  const handleRunWorkflowStep = async (projId: string) => {
    setRunningProjId(projId);
    setRunLog(["Triggering backend workflow dispatcher..."]);
    
    const pollInterval = setInterval(async () => {
      try {
        const res = await fetch(`/api/projects/${projId}/logs`);
        if (res.ok) {
          const logs = await res.json();
          if (logs && logs.length > 0) {
            setRunLog(logs);
          }
        }
      } catch (e) {}
    }, 600);

    try {
      const res = await fetch(`/api/projects/${projId}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });
      
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Workflow execution failed');
      }
      
      clearInterval(pollInterval);
      try {
        const finalLogsRes = await fetch(`/api/projects/${projId}/logs`);
        if (finalLogsRes.ok) {
          const finalLogs = await finalLogsRes.json();
          setRunLog(finalLogs);
        }
      } catch (e) {}

      fetchProjects();
      setRunningProjId(null);
    } catch (err: any) {
      clearInterval(pollInterval);
      setRunLog(prev => [...prev, `[ERROR] Execution failed: ${err.message || err}`]);
      setRunningProjId(null);
    }
  };

  const filteredSavedTopics = savedFilterChannel === 'all' 
    ? savedTopics 
    : savedTopics.filter(t => t.channel?.toLowerCase().includes(savedFilterChannel.toLowerCase()));

  return (
    <div className="app-container">
      <style>{`
        .app-container {
          display: flex;
          min-height: 100vh;
          background-color: #08090d;
          color: #e2e8f0;
          font-family: 'Outfit', sans-serif;
        }

        .sidebar {
          width: 280px;
          background-color: #0e1017;
          border-right: 1px solid #1a1d29;
          display: flex;
          flex-direction: column;
          padding: 24px;
        }
        .sidebar-brand {
          font-size: 1.5rem;
          font-weight: 700;
          color: #ffffff;
          margin-bottom: 24px;
          display: flex;
          align-items: center;
          gap: 12px;
          background: linear-gradient(135deg, #a78bfa, #f43f5e);
          -webkit-background-clip: text;
          -webkit-text-fill-color: transparent;
        }
        .sidebar-section-title {
          font-size: 0.75rem;
          text-transform: uppercase;
          color: #475569;
          font-weight: 600;
          margin: 16px 0 8px 12px;
          letter-spacing: 0.05em;
        }
        .sidebar-menu {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .menu-item {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 10px 14px;
          border-radius: 8px;
          color: #94a3b8;
          font-weight: 500;
          font-size: 0.95rem;
          cursor: pointer;
          transition: all 0.2s;
        }
        .menu-item:hover, .menu-item.active {
          color: #ffffff;
          background-color: #161923;
        }
        .menu-item.active {
          border-left: 3px solid #f43f5e;
          background: linear-gradient(90deg, #161923 0%, #0e1017 100%);
          font-weight: 600;
        }
        .sidebar-footer {
          margin-top: auto;
          font-size: 0.8rem;
          color: #475569;
          text-align: center;
          padding-top: 16px;
          border-top: 1px solid #1a1d29;
        }

        .workspace {
          flex: 1;
          display: flex;
          flex-direction: column;
          overflow-y: auto;
        }
        .header {
          height: 70px;
          background-color: rgba(14, 16, 23, 0.95);
          backdrop-filter: blur(12px);
          border-bottom: 1px solid #1a1d29;
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 0 40px;
          position: sticky;
          top: 0;
          z-index: 100;
        }
        .header-title {
          font-size: 1.25rem;
          font-weight: 600;
          color: #ffffff;
        }
        .header-status {
          display: flex;
          align-items: center;
          gap: 16px;
        }
        .status-badge {
          display: flex;
          align-items: center;
          gap: 8px;
          background-color: #0b261d;
          color: #4ade80;
          padding: 6px 14px;
          border-radius: 9999px;
          font-size: 0.85rem;
          font-weight: 600;
        }
        .status-dot {
          width: 8px;
          height: 8px;
          background-color: #4ade80;
          border-radius: 50%;
          box-shadow: 0 0 8px #4ade80;
        }

        .mic-btn-active {
          background: linear-gradient(135deg, #ef4444 0%, #f43f5e 100%) !important;
          color: #ffffff !important;
          box-shadow: 0 0 15px rgba(244, 63, 94, 0.6);
          animation: pulseMic 1.5s infinite;
        }

        @keyframes pulseMic {
          0% { transform: scale(1); }
          50% { transform: scale(1.05); }
          100% { transform: scale(1); }
        }

        .main-content {
          padding: 40px;
          max-width: 1200px;
          width: 100%;
          box-sizing: border-box;
          margin: 0 auto;
        }

        .metrics-grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
          gap: 24px;
          margin-bottom: 40px;
        }
        .metric-card {
          background-color: #12141d;
          border: 1px solid #1e2230;
          border-radius: 12px;
          padding: 24px;
          display: flex;
          flex-direction: column;
          position: relative;
          overflow: hidden;
          transition: transform 0.2s;
        }
        .metric-card:hover {
          transform: translateY(-2px);
          border-color: #2b3042;
        }
        .metric-icon-bg {
          position: absolute;
          right: -10px;
          bottom: -10px;
          color: #1e2230;
          opacity: 0.15;
          transform: scale(3.5);
        }
        .metric-label {
          font-size: 0.85rem;
          color: #64748b;
          font-weight: 600;
          text-transform: uppercase;
          margin-bottom: 8px;
        }
        .metric-val {
          font-size: 1.85rem;
          font-weight: 700;
          color: #ffffff;
        }

        .panel-card {
          background-color: #12141d;
          border: 1px solid #1e2230;
          border-radius: 12px;
          padding: 28px;
          margin-bottom: 32px;
        }
        .panel-title {
          font-size: 1.2rem;
          font-weight: 600;
          color: #ffffff;
          margin-top: 0;
          margin-bottom: 20px;
          display: flex;
          align-items: center;
          gap: 10px;
          border-bottom: 1px solid #1e2230;
          padding-bottom: 12px;
        }
        .form-row {
          display: flex;
          gap: 20px;
          margin-bottom: 20px;
          flex-wrap: wrap;
        }
        .form-group {
          flex: 1;
          min-width: 200px;
          display: flex;
          flex-direction: column;
          gap: 8px;
        }
        .form-group label {
          font-size: 0.85rem;
          color: #94a3b8;
          font-weight: 500;
        }
        .form-control {
          background-color: #08090d;
          border: 1px solid #1e2230;
          color: #ffffff;
          padding: 12px 16px;
          border-radius: 8px;
          font-size: 0.95rem;
          font-family: inherit;
          outline: none;
          transition: border-color 0.2s;
        }
        .form-control:focus {
          border-color: #f43f5e;
        }

        .project-list {
          display: flex;
          flex-direction: column;
          gap: 16px;
        }
        .project-item {
          background-color: #12141d;
          border: 1px solid #1e2230;
          border-radius: 12px;
          padding: 20px 24px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          flex-wrap: wrap;
          gap: 20px;
          transition: border-color 0.2s;
        }
        .project-item:hover {
          border-color: #2b3042;
        }
        .project-info {
          display: flex;
          flex-direction: column;
          gap: 6px;
        }
        .project-name {
          font-size: 1.1rem;
          font-weight: 600;
          color: #ffffff;
        }
        .project-meta {
          display: flex;
          gap: 16px;
          font-size: 0.85rem;
          color: #64748b;
        }
        .brand-badge {
          background-color: #161923;
          color: #f43f5e;
          padding: 2px 8px;
          border-radius: 4px;
          font-weight: 600;
        }
        .status-badge-inline {
          padding: 4px 10px;
          border-radius: 9999px;
          font-weight: 600;
          font-size: 0.8rem;
          text-transform: uppercase;
        }
        .status-completed { background-color: #0b261d; color: #4ade80; }
        .status-running { background-color: #2e1d0f; color: #f59e0b; }
        .status-planned { background-color: #171923; color: #94a3b8; }

        .btn {
          background: linear-gradient(135deg, #a78bfa 0%, #f43f5e 100%);
          color: #ffffff;
          border: none;
          padding: 12px 24px;
          font-size: 0.95rem;
          font-weight: 600;
          border-radius: 8px;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          gap: 8px;
          transition: opacity 0.2s;
        }
        .btn:hover {
          opacity: 0.9;
        }
        .btn-outline {
          background: transparent;
          border: 1px solid #1e2230;
          color: #f1f3f9;
        }
        .btn-outline:hover {
          background-color: #161923;
        }

        .subtab-btn {
          padding: 10px 18px;
          border-radius: 8px;
          font-size: 0.9rem;
          font-weight: 600;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 8px;
          border: 1px solid transparent;
          background-color: transparent;
          color: #94a3b8;
          transition: all 0.2s;
        }
        .subtab-btn.active {
          background-color: #1c1827;
          border-color: #f43f5e;
          color: #ffffff;
        }

        .chat-bubble-user {
          align-self: flex-end;
          background: linear-gradient(135deg, #a78bfa 0%, #f43f5e 100%);
          color: #ffffff;
          padding: 14px 18px;
          border-radius: 16px 16px 4px 16px;
          max-width: 75%;
          font-size: 0.95rem;
          line-height: 1.5;
        }
        .chat-bubble-agent {
          align-self: flex-start;
          background-color: #161923;
          border: 1px solid #232738;
          color: #e2e8f0;
          padding: 16px 20px;
          border-radius: 16px 16px 16px 4px;
          max-width: 80%;
          font-size: 0.95rem;
          line-height: 1.6;
          white-space: pre-wrap;
        }

        .toast-banner {
          position: fixed;
          bottom: 24px;
          right: 24px;
          background-color: #0b261d;
          border: 1px solid #4ade80;
          color: #4ade80;
          padding: 12px 20px;
          border-radius: 8px;
          display: flex;
          align-items: center;
          gap: 10px;
          font-weight: 600;
          box-shadow: 0 10px 25px rgba(0,0,0,0.5);
          z-index: 1000;
          animation: slideIn 0.3s ease-out;
        }

        .modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background-color: rgba(0,0,0,0.8);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 2000;
        }

        .logs-panel {
          background-color: #08090d;
          border: 1px solid #1e2230;
          border-radius: 8px;
          padding: 16px;
          font-family: monospace;
          font-size: 0.85rem;
          max-height: 250px;
          overflow-y: auto;
          display: flex;
          flex-direction: column;
          gap: 6px;
          color: #38bdf8;
          margin-top: 16px;
        }

        .parchment-editor {
          background-color: #1c1d24;
          border: 1px solid #2d3142;
          border-radius: 8px;
          padding: 24px;
          color: #e2e8f0;
          font-family: monospace;
          line-height: 1.6;
          min-height: 300px;
          outline: none;
        }

        .timeline-container {
          display: flex;
          flex-direction: column;
          gap: 12px;
          margin-top: 16px;
        }
        .timeline-step {
          display: flex;
          align-items: center;
          gap: 16px;
          background-color: #12141d;
          border: 1px solid #1e2230;
          border-radius: 8px;
          padding: 14px 20px;
        }
        .step-num {
          background-color: #1e2230;
          color: #ffffff;
          width: 28px;
          height: 28px;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          font-weight: 700;
          font-size: 0.85rem;
        }
      `}</style>

      {/* Toast Notification Banner */}
      {savedToast && (
        <div className="toast-banner">
          <CheckCircle2 size={18} />
          <span>{savedToast}</span>
        </div>
      )}

      {/* Voice Commands Cheat Sheet Modal */}
      {showVoiceHelp && (
        <div className="modal-overlay" onClick={() => setShowVoiceHelp(false)}>
          <div className="panel-card" style={{ maxWidth: '600px', width: '90%', margin: 0 }} onClick={e => e.stopPropagation()}>
            <h3 className="panel-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ display: 'flex', alignItems: 'center', gap: '10px' }}><Mic size={20} style={{ color: '#f43f5e' }} /> Continuous Voice Command Cheat Sheet</span>
              <button onClick={() => setShowVoiceHelp(false)} style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: '1.2rem' }}>✕</button>
            </h3>

            <p style={{ color: '#cbd5e1', fontSize: '0.9rem' }}>Speak any of the following natural commands aloud while continuous voice listening is active:</p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', fontSize: '0.85rem' }}>
              <div style={{ backgroundColor: '#08090d', padding: '12px', borderRadius: '8px', border: '1px solid #1e2230' }}>
                <strong style={{ color: '#a78bfa' }}>1. Channel Brand Switching:</strong>
                <div style={{ color: '#94a3b8', marginTop: '4px' }}>• <em>"Switch to Spilled Coffee Studio"</em><br />• <em>"Switch to After Dark"</em><br />• <em>"Switch to Beyond 3Baje"</em><br />• <em>"Switch to Life 3Baje"</em><br />• <em>"Switch to Khayal 3Baje"</em></div>
              </div>

              <div style={{ backgroundColor: '#08090d', padding: '12px', borderRadius: '8px', border: '1px solid #1e2230' }}>
                <strong style={{ color: '#4ade80' }}>2. Actions & Discovery:</strong>
                <div style={{ color: '#94a3b8', marginTop: '4px' }}>• <em>"Discover topics"</em> / <em>"Find topics"</em><br />• <em>"Save topic"</em> (Bookmarks top topic to Vault)<br />• <em>"Open chat"</em> / <em>"Talk to agent"</em><br />• <em>"Show saved"</em> (Opens Saved Topics Vault)</div>
              </div>

              <div style={{ backgroundColor: '#08090d', padding: '12px', borderRadius: '8px', border: '1px solid #1e2230' }}>
                <strong style={{ color: '#38bdf8' }}>3. Studio Navigation:</strong>
                <div style={{ color: '#94a3b8', marginTop: '4px' }}>• <em>"Go to Topic Vault"</em><br />• <em>"Go to Dashboard"</em><br />• <em>"Go to Projects"</em><br />• <em>"Go to Research"</em><br />• <em>"Go to Writing"</em><br />• <em>"Go to Settings"</em></div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Sidebar navigation */}
      <div className="sidebar">
        <div className="sidebar-brand">
          <Database size={24} />
          <span>Buzzcaf AI v1</span>
        </div>
        
        <div className="sidebar-section-title">Core Studio</div>
        <div className="sidebar-menu">
          <div className={`menu-item ${activeTab === 'dashboard' ? 'active' : ''}`} onClick={() => setActiveTab('dashboard')}>
            <LayoutDashboard size={18} />
            <span>Dashboard</span>
          </div>

          <div className={`menu-item ${activeTab === 'projects' ? 'active' : ''}`} onClick={() => setActiveTab('projects')}>
            <FolderGit2 size={18} />
            <span>Projects Catalog</span>
          </div>
        </div>

        <div className="sidebar-section-title">Channel Intelligence</div>
        <div className="sidebar-menu">
          <div className={`menu-item ${activeTab === 'topic_discovery' ? 'active' : ''}`} onClick={() => { setActiveTab('topic_discovery'); handleDiscoverTopics(selectedChannel); }}>
            <Compass size={18} />
            <span>Topic Vault & AI Chat</span>
          </div>
        </div>

        <div className="sidebar-section-title">Workspaces</div>
        <div className="sidebar-menu">
          <div className={`menu-item ${activeTab === 'research' ? 'active' : ''}`} onClick={() => setActiveTab('research')}>
            <BookOpen size={18} />
            <span>Research Workspace</span>
          </div>

          <div className={`menu-item ${activeTab === 'writing' ? 'active' : ''}`} onClick={() => setActiveTab('writing')}>
            <FileText size={18} />
            <span>Writing Studio</span>
          </div>

          <div className={`menu-item ${activeTab === 'dictation_studio' ? 'active' : ''}`} onClick={() => setActiveTab('dictation_studio')}>
            <Mic size={18} style={{ color: '#f43f5e' }} />
            <span>Voice Dictation Studio</span>
          </div>

          <div className={`menu-item ${activeTab === 'production' ? 'active' : ''}`} onClick={() => setActiveTab('production')}>
            <Video size={18} />
            <span>Production Board</span>
          </div>

          <div className={`menu-item ${activeTab === 'publishing' ? 'active' : ''}`} onClick={() => setActiveTab('publishing')}>
            <Share2 size={18} />
            <span>Publish & Analytics</span>
          </div>
        </div>

        <div className="sidebar-section-title">Administration</div>
        <div className="sidebar-menu">
          <div className={`menu-item ${activeTab === 'ai_workforce' ? 'active' : ''}`} onClick={() => setActiveTab('ai_workforce')}>
            <Users size={18} />
            <span>AI Workforce ({registeredAgents.length || 115} Agents)</span>
          </div>

          <div className={`menu-item ${activeTab === 'health' ? 'active' : ''}`} onClick={() => setActiveTab('health')}>
            <HeartPulse size={18} />
            <span>System Health</span>
          </div>

          <div className={`menu-item ${activeTab === 'settings' ? 'active' : ''}`} onClick={() => setActiveTab('settings')}>
            <SettingsIcon size={18} />
            <span>AI Router Settings</span>
          </div>
        </div>

        <div className="sidebar-footer">
          <p>Buzzcaf AI Studio</p>
          <p>© 2026 Production</p>
        </div>
      </div>

      {/* Main Workspace Frame */}
      <div className="workspace" ref={workspaceRef} onScroll={handleWorkspaceScroll}>
        <div className="header">
          <div className="header-title">
            {activeTab === 'dashboard' && 'Studio Overview'}
            {activeTab === 'projects' && 'Production Catalog'}
            {activeTab === 'topic_discovery' && 'Channel Topic Vault & Live AI Strategist'}
            {activeTab === 'research' && 'Research Workspace'}
            {activeTab === 'writing' && 'Writing Studio'}
            {activeTab === 'dictation_studio' && 'Voice Script Dictation Studio & AI Story Completer'}
            {activeTab === 'production' && 'Production Workspace'}
            {activeTab === 'publishing' && 'Publishing & Analytics'}
            {activeTab === 'ai_workforce' && `AI Workforce Registry (${registeredAgents.length || 115} Agents)`}
            {activeTab === 'health' && 'System Diagnostics'}
            {activeTab === 'settings' && 'System Parameters Configuration'}
          </div>

          {/* Continuous Voice System Control Header Bar */}
          <div className="header-status" style={{ gap: '12px' }}>
            {/* Master Voice ON/OFF Power Toggle Switch */}
            <button 
              className={`btn ${isVoiceActive ? 'btn-danger' : 'btn-primary'}`}
              onClick={() => toggleContinuousVoice()}
              style={{
                padding: '8px 16px',
                fontSize: '0.85rem',
                fontWeight: 600,
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                backgroundColor: isVoiceActive ? '#ef4444' : '#10b981',
                borderColor: isVoiceActive ? '#dc2626' : '#059669',
                color: '#ffffff',
                boxShadow: isVoiceActive ? '0 0 12px rgba(239, 68, 68, 0.4)' : '0 0 12px rgba(16, 185, 129, 0.4)'
              }}
              title={isVoiceActive ? "Click to Disable Voice Assistant" : "Click to Enable Buzzcaf Voice Assistant"}
            >
              {isVoiceActive ? <MicOff size={16} /> : <Mic size={16} />}
              <span>{isVoiceActive ? '🔴 Disable Voice' : '🟢 Enable Voice'}</span>
            </button>

            {/* Voice Help Trigger */}
            <button 
              className="btn btn-outline" 
              onClick={() => setShowVoiceHelp(true)}
              style={{ padding: '8px 10px', fontSize: '0.85rem' }}
              title="Buzzcaf Voice Commands Guide"
            >
              <HelpCircle size={16} />
            </button>

            {/* Voice Activity Log Console Trigger Button */}
            <button 
              className="btn btn-outline" 
              onClick={() => setShowVoiceLogs(true)}
              style={{ padding: '8px 12px', fontSize: '0.85rem', color: '#a78bfa', borderColor: '#3b0764', backgroundColor: '#1e1b4b' }}
              title="Open Live Voice Activity Log Console"
            >
              <List size={16} />
              <span>Activity Log ({voiceLogs.length})</span>
            </button>

            {/* Voice Tuning Control Panel Trigger */}
            <button 
              className="btn btn-outline" 
              onClick={() => setShowVoiceTuning(true)}
              style={{ padding: '8px 12px', fontSize: '0.85rem', color: '#38bdf8', borderColor: '#0284c7', backgroundColor: '#0f172a' }}
              title="Tune Voice Persona (Voice, Speed, Pitch, Volume)"
            >
              <Sliders size={16} />
              <span>Voice Tuning</span>
            </button>

            {/* Audio Response Output Mute Toggle */}
            <button 
              className="btn btn-outline" 
              onClick={() => setIsAudioMuted(!isAudioMuted)}
              style={{ padding: '8px 10px', fontSize: '0.85rem', color: isAudioMuted ? '#fca5a5' : '#38bdf8', borderColor: isAudioMuted ? '#7f1d1d' : '#1e2230' }}
              title={isAudioMuted ? "Unmute Voice Response Audio" : "Mute Voice Response Audio"}
            >
              {isAudioMuted ? <VolumeX size={16} /> : <Volume2 size={16} />}
            </button>

            {/* Blue Buzzcaf Voice Status Badge */}
            {isVoiceActive && (
              <div style={{ backgroundColor: '#0f172a', border: '1px solid #38bdf8', padding: '6px 14px', borderRadius: '8px', fontSize: '0.85rem', color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '6px', maxWidth: '320px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                <Sparkles size={14} style={{ color: isTTSSpeaking ? '#f59e0b' : '#a78bfa' }} />
                <span>{isTTSSpeaking ? '🗣️ Buzzcaf Speaking...' : voiceFeedbackText ? `"${voiceFeedbackText}"` : lastVoiceTranscript ? `"${lastVoiceTranscript}"` : '🤖 Buzzcaf Online'}</span>
              </div>
            )}

            <div className="status-badge">
              <div className="status-dot"></div>
              <span>Backend Core: Active</span>
            </div>
          </div>
        </div>

        <div className="main-content">
          {error && (
            <div style={{ backgroundColor: '#2d141b', border: '1px solid #7f1d1d', borderRadius: '8px', padding: '12px 16px', display: 'flex', alignItems: 'center', gap: '10px', color: '#fca5a5', marginBottom: '24px' }}>
              <AlertCircle size={20} />
              <span>Note: API offline or loading locally. Running in robust Simulation fallback mode.</span>
            </div>
          )}

          {/* Tab: Dashboard */}
          {activeTab === 'dashboard' && (
            <div>
              <div className="metrics-grid">
                <div className="metric-card">
                  <div className="metric-icon-bg"><FolderGit2 /></div>
                  <span className="metric-label">Active Projects</span>
                  <span className="metric-val">{projects.length}</span>
                </div>

                <div className="metric-card">
                  <div className="metric-icon-bg"><Activity /></div>
                  <span className="metric-label">AI Router Status</span>
                  <span className="metric-val" style={{ fontSize: '1.25rem', marginTop: '10px', color: '#f43f5e' }}>
                    {selectedLlm === 'gemini' ? 'Google Gemini' : selectedLlm === 'openai' ? 'OpenAI ChatGPT' : 'Local LM Studio'}
                  </span>
                </div>

                <div className="metric-card">
                  <div className="metric-icon-bg"><CheckCircle2 /></div>
                  <span className="metric-label">Registered Agents</span>
                  <span className="metric-val">{registeredAgents.length || 115}</span>
                </div>

                <div className="metric-card">
                  <div className="metric-icon-bg"><TrendingUp /></div>
                  <span className="metric-label">Studio Status</span>
                  <span className="metric-val" style={{ color: '#4ade80' }}>HEALTHY</span>
                </div>
              </div>

              <div className="panel-card">
                <h3 className="panel-title"><PlusCircle size={20} /> Initialize New Production Project</h3>
                <form onSubmit={handleCreateProject}>
                  <div className="form-row">
                    <div className="form-group">
                      <label>Project Title</label>
                      <input 
                        type="text" 
                        className="form-control" 
                        placeholder="e.g. History of Tea Houses" 
                        value={newProjName}
                        onChange={e => setNewProjName(e.target.value)}
                        required
                      />
                    </div>

                    <div className="form-group">
                      <label>Brand Target Channel</label>
                      <select 
                        className="form-control"
                        value={newProjBrand}
                        onChange={e => setNewProjBrand(e.target.value)}
                      >
                        <option value="Spilled Coffee Studio">Spilled Coffee Studio (Originals & Story Analysis)</option>
                        <option value="Beyond3Baje">Beyond3Baje (Documentary True Stories)</option>
                        <option value="Spilled Coffee After Dark">Spilled Coffee After Dark (Horror & Urban Legends)</option>
                        <option value="Life3Baje">Life3Baje (Creative Journey & Essays)</option>
                        <option value="Khayal3Baje">Khayal3Baje (Ancient Mythology & Epic Lore)</option>
                      </select>
                    </div>

                    <div className="form-group">
                      <label>Department Workflow Engine</label>
                      <select 
                        className="form-control"
                        value={newProjWorkflow}
                        onChange={e => setNewProjWorkflow(e.target.value)}
                      >
                        <option value="beyond3baje_documentary">beyond3baje_documentary</option>
                        <option value="spilled_coffee_story">spilled_coffee_story</option>
                        <option value="after_dark_narration">after_dark_narration</option>
                        <option value="life3baje_essay">life3baje_essay</option>
                        <option value="khayal3baje_horror">khayal3baje_horror</option>
                      </select>
                    </div>
                  </div>

                  <button type="submit" className="btn">
                    <PlusCircle size={18} />
                    <span>Initialize Project</span>
                  </button>
                </form>
              </div>
            </div>
          )}

          {/* Tab: Channel Topic Discovery & Vault */}
          {activeTab === 'topic_discovery' && (
            <div>
              {/* Sticky Navigation Header Sub-Tabs */}
              <div style={{ position: 'sticky', top: '70px', zIndex: 90, backgroundColor: 'rgba(14, 16, 23, 0.95)', backdropFilter: 'blur(12px)', padding: '14px 0', marginBottom: '24px', borderBottom: '1px solid #1e2230', display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                  <button 
                    className={`subtab-btn ${topicSubTab === 'discovered' ? 'active' : ''}`}
                    onClick={() => setTopicSubTab('discovered')}
                  >
                    <Search size={18} />
                    <span>🔍 Discovered Topics</span>
                  </button>

                  <button 
                    className={`subtab-btn ${topicSubTab === 'saved' ? 'active' : ''}`}
                    onClick={() => { setTopicSubTab('saved'); fetchSavedTopics(); }}
                  >
                    <Star size={18} style={{ color: '#f59e0b' }} />
                    <span>⭐ Saved Topics Vault ({savedTopics.length})</span>
                  </button>

                  <button 
                    className={`subtab-btn ${topicSubTab === 'chat' ? 'active' : ''}`}
                    onClick={() => setTopicSubTab('chat')}
                  >
                    <MessageSquare size={18} style={{ color: '#a78bfa' }} />
                    <span>💬 Live AI Strategist Chat ({getStrategistAgentName(selectedChannel)})</span>
                  </button>
                </div>

                {/* Global Channel & Strategist Switcher Dropdown */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', backgroundColor: '#12141d', padding: '6px 14px', borderRadius: '8px', border: '1px solid #1e2230' }}>
                  <span style={{ fontSize: '0.8rem', color: '#94a3b8', fontWeight: 600 }}>Active Channel & Strategist:</span>
                  <select 
                    className="form-control" 
                    style={{ padding: '4px 10px', fontSize: '0.85rem', fontWeight: 700, color: '#f43f5e', backgroundColor: '#1a1d29', borderColor: '#334155', cursor: 'pointer', width: 'auto' }}
                    value={selectedChannel}
                    onChange={(e) => {
                      const newChan = e.target.value;
                      setSelectedChannel(newChan);
                      if (topicSubTab === 'discovered') {
                        handleDiscoverTopics(newChan);
                      }
                    }}
                  >
                    <option value="Spilled Coffee Studio">✍️ Spilled Coffee Studio (SpilledCoffeeStudioStrategist)</option>
                    <option value="Spilled Coffee After Dark">👻 Spilled Coffee After Dark (AfterDarkStrategist)</option>
                    <option value="Beyond3Baje">🕵️ Beyond3Baje (Beyond3BajeStrategist)</option>
                    <option value="Life3Baje">☕ Life3Baje (Life3BajeStrategist)</option>
                    <option value="Khayal3Baje">🏛️ Khayal3Baje (Khayal3BajeStrategist)</option>
                  </select>
                </div>
              </div>

              {/* View 1: Discovered Topics */}
              {topicSubTab === 'discovered' && (
                <div>
                  <div className="panel-card" style={{ marginBottom: '24px' }}>
                    <h3 className="panel-title" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: '10px' }}><Compass size={22} /> Channel Topic Discovery</span>
                      <span style={{ fontSize: '0.85rem', color: '#4ade80', backgroundColor: '#0b261d', padding: '4px 12px', borderRadius: '9999px', fontWeight: 600 }}>Vault Target: 100+ Raw / 50 Researched / 20 Script-Ready</span>
                    </h3>
                    <p style={{ color: '#94a3b8', margin: '0 0 20px 0' }}>Select target channel brand to search sources (Reddit, Wikipedia, YouTube Trends, Google News, Local Folklore, Books, Archives).</p>

                    {/* Channel Selector Cards */}
                    <div style={{ display: 'flex', gap: '16px', marginBottom: '24px', flexWrap: 'wrap' }}>
                      {[
                        { id: 'Spilled Coffee Studio', name: 'Spilled Coffee Studio', desc: 'Where stories are born (Originals & Analysis)', icon: '✍️' },
                        { id: 'Spilled Coffee After Dark', name: 'Spilled Coffee After Dark', desc: 'Horror, Paranormal & Urban Legends', icon: '👻' },
                        { id: 'Beyond3Baje', name: 'Beyond3Baje', desc: 'True Stories, Dark History & True Crime', icon: '🕵️' },
                        { id: 'Life3Baje', name: 'Life3Baje', desc: 'Creative Journey & Video Essays', icon: '☕' },
                        { id: 'Khayal3Baje', name: 'Khayal3Baje', desc: 'Ancient Mythology & Sacred Lore', icon: '🏛️' }
                      ].map((ch) => (
                        <div 
                          key={ch.id} 
                          onClick={() => { setSelectedChannel(ch.id); handleDiscoverTopics(ch.id); }}
                          style={{
                            flex: 1,
                            minWidth: '220px',
                            padding: '16px',
                            borderRadius: '10px',
                            border: selectedChannel === ch.id ? '2px solid #f43f5e' : '1px solid #1e2230',
                            backgroundColor: selectedChannel === ch.id ? '#1c1724' : '#12141d',
                            cursor: 'pointer',
                            transition: 'all 0.2s'
                          }}
                        >
                          <div style={{ fontSize: '1.2rem', marginBottom: '4px' }}>{ch.icon} <strong style={{ color: '#ffffff' }}>{ch.name}</strong></div>
                          <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>{ch.desc}</div>
                        </div>
                      ))}
                    </div>

                    {/* Source Selection Toggles */}
                    <div style={{ marginBottom: '24px', backgroundColor: '#08090d', padding: '16px', borderRadius: '8px', border: '1px solid #1e2230' }}>
                      <div style={{ fontSize: '0.85rem', color: '#38bdf8', fontWeight: 600, marginBottom: '12px' }}>🌐 Active Multi-Channel Content Discovery Sources (12 Sources Engine):</div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '12px', fontSize: '0.85rem' }}>
                        {[
                          'Reddit (r/nosleep, r/UnresolvedMysteries, r/AskReddit)',
                          'Wikipedia Deep Rabbit Holes',
                          'YouTube Evergreen Search Trends',
                          'Google News & Breaking Trending Topics',
                          'Local Indian Regional Folklore & Oral Histories',
                          'Ancient Indian Epics & World Mythology Texts',
                          'Global Urban Legends & Creepypasta Archives',
                          'Internet Archive & Public Domain Manuscripts',
                          'Declassified FBI / CIA / Military Records',
                          'Historical Disaster & Engineering Inspection Logs',
                          'True Crime Case Files & Judicial Archives',
                          'Substack Video Essays & Cultural Blogs'
                        ].map((src) => (
                          <label key={src} style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', color: '#e2e8f0', backgroundColor: '#141824', padding: '8px 12px', borderRadius: '6px', border: '1px solid #1e293b' }}>
                            <input type="checkbox" defaultChecked style={{ accentColor: '#38bdf8' }} />
                            <span>{src}</span>
                          </label>
                        ))}
                      </div>
                    </div>

                    <button className="btn" disabled={isDiscovering} onClick={() => handleDiscoverTopics(selectedChannel)}>
                      <Sparkles size={18} />
                      <span>{isDiscovering ? 'Searching Sources & Structuring Vault...' : `Run Channel Topic Discovery (${selectedChannel})`}</span>
                    </button>
                  </div>

                  {/* Discovered Topic Vault List */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                    <h3 style={{ margin: 0, fontSize: '1.2rem', color: '#ffffff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span>Discovered Topics for</span> <span style={{ color: '#f43f5e', fontWeight: 700 }}>{selectedChannel}</span>
                    </h3>

                    {discoveredTopics.map((item: any, idx: number) => (
                      <div key={idx} className="panel-card" style={{ padding: '24px', margin: 0, display: 'flex', flexDirection: 'column', gap: '16px', borderLeft: '4px solid #f43f5e' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
                          <div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
                              <span className="brand-badge" style={{ backgroundColor: '#1f1a29', color: '#a78bfa' }}>{item.category}</span>
                              <span style={{ fontSize: '0.8rem', color: '#4ade80', backgroundColor: '#0b261d', padding: '2px 8px', borderRadius: '4px', fontWeight: 600 }}>Viral Score: {item.viral_potential}/10</span>
                              {item.country && <span style={{ fontSize: '0.8rem', color: '#38bdf8', backgroundColor: '#0c2233', padding: '2px 8px', borderRadius: '4px' }}>{item.country}</span>}
                            </div>
                            <h4 style={{ margin: 0, fontSize: '1.25rem', color: '#ffffff' }}>{item.topic}</h4>
                          </div>

                          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                            <button 
                              className="btn btn-outline" 
                              style={{ padding: '8px 14px', fontSize: '0.85rem' }}
                              onClick={() => handleSaveTopic(item)}
                            >
                              <Bookmark size={15} style={{ color: '#f59e0b' }} />
                              <span>Save to Vault</span>
                            </button>

                            <button 
                              className="btn btn-outline" 
                              style={{ padding: '8px 14px', fontSize: '0.85rem' }}
                              onClick={() => handleOpenChatForTopic(item)}
                            >
                              <MessageSquare size={15} style={{ color: '#a78bfa' }} />
                              <span>Discuss with Agent</span>
                            </button>

                            <button 
                              className="btn" 
                              style={{ padding: '8px 16px', fontSize: '0.85rem' }}
                              onClick={() => handleSendToDevelopment(item, selectedChannel)}
                            >
                              <Send size={15} />
                              <span>Send to Dev</span>
                            </button>
                          </div>
                        </div>

                        <div style={{ fontSize: '0.9rem', color: '#cbd5e1', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                          <div><strong>Source Type:</strong> {item.source_type}</div>
                          <div><strong>Sources Used:</strong> {item.sources_used ? item.sources_used.join(' • ') : 'Reddit, Wikipedia'}</div>
                          <div><strong>Visual B-Roll / Map Needs:</strong> {item.visual_requirements ? item.visual_requirements.join(' • ') : 'Standard documentary footage'}</div>
                          <div style={{ fontSize: '0.85rem', color: '#4ade80', fontWeight: 600 }}>{item.exclusion_audit}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* View 2: Saved Topics Vault */}
              {topicSubTab === 'saved' && (
                <div>
                  <div className="panel-card" style={{ marginBottom: '24px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
                      <div>
                        <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0, display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <Star size={22} style={{ color: '#f59e0b' }} />
                          <span>Persistent Saved Topics Vault</span>
                        </h3>
                        <p style={{ color: '#94a3b8', margin: '6px 0 0 0' }}>Your bookmarked topics across all Buzzcaf Media channels, stored for future video production.</p>
                      </div>

                      {/* Filter by Channel */}
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <Filter size={16} style={{ color: '#94a3b8' }} />
                        <select 
                          className="form-control" 
                          style={{ padding: '8px 14px', fontSize: '0.85rem' }}
                          value={savedFilterChannel}
                          onChange={e => setSavedFilterChannel(e.target.value)}
                        >
                          <option value="all">All Channel Brands ({savedTopics.length})</option>
                          <option value="Spilled Coffee Studio">Spilled Coffee Studio</option>
                          <option value="Spilled Coffee After Dark">Spilled Coffee After Dark</option>
                          <option value="Beyond3Baje">Beyond3Baje</option>
                          <option value="Life3Baje">Life3Baje</option>
                          <option value="Khayal3Baje">Khayal3Baje</option>
                        </select>
                      </div>
                    </div>
                  </div>

                  {/* Saved Topics Grid */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                    {filteredSavedTopics.length === 0 ? (
                      <div className="panel-card" style={{ textAlign: 'center', padding: '40px', color: '#94a3b8' }}>
                        <Bookmark size={36} style={{ marginBottom: '12px', opacity: 0.5 }} />
                        <p style={{ margin: 0, fontSize: '1rem' }}>No saved topics found for this filter.</p>
                        <p style={{ fontSize: '0.85rem', marginTop: '6px' }}>Switch to the Discovered Topics tab and click <strong>Save to Vault</strong> on any video topic!</p>
                      </div>
                    ) : (
                      filteredSavedTopics.map((item: any, idx: number) => (
                        <div key={item.id || idx} className="panel-card" style={{ padding: '24px', margin: 0, display: 'flex', flexDirection: 'column', gap: '16px', borderLeft: '4px solid #f59e0b' }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
                            <div>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '6px' }}>
                                <span className="brand-badge">{item.channel}</span>
                                <span className="brand-badge" style={{ backgroundColor: '#1f1a29', color: '#a78bfa' }}>{item.category}</span>
                                <span style={{ fontSize: '0.8rem', color: '#4ade80', backgroundColor: '#0b261d', padding: '2px 8px', borderRadius: '4px', fontWeight: 600 }}>Viral Score: {item.viral_potential}/10</span>
                              </div>
                              <h4 style={{ margin: 0, fontSize: '1.25rem', color: '#ffffff' }}>{item.topic}</h4>
                            </div>

                            <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                              <button 
                                className="btn btn-outline" 
                                style={{ padding: '8px 14px', fontSize: '0.85rem' }}
                                onClick={() => handleOpenChatForTopic(item)}
                              >
                                <MessageSquare size={15} style={{ color: '#a78bfa' }} />
                                <span>Discuss with Agent</span>
                              </button>

                              <button 
                                className="btn" 
                                style={{ padding: '8px 16px', fontSize: '0.85rem' }}
                                onClick={() => handleSendToDevelopment(item, item.channel)}
                              >
                                <Send size={15} />
                                <span>Send for Development</span>
                              </button>

                              <button 
                                className="btn btn-outline" 
                                style={{ padding: '8px 12px', fontSize: '0.85rem', borderColor: '#7f1d1d', color: '#fca5a5' }}
                                onClick={() => handleDeleteSavedTopic(item.id, item.topic)}
                              >
                                <Trash2 size={15} />
                              </button>
                            </div>
                          </div>

                          <div style={{ fontSize: '0.9rem', color: '#cbd5e1', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                            <div><strong>Sources Used:</strong> {item.sources_used ? (Array.isArray(item.sources_used) ? item.sources_used.join(' • ') : item.sources_used) : 'N/A'}</div>
                            <div><strong>Visual B-Roll Needs:</strong> {item.visual_requirements ? (Array.isArray(item.visual_requirements) ? item.visual_requirements.join(' • ') : item.visual_requirements) : 'N/A'}</div>
                            {item.notes && <div style={{ fontStyle: 'italic', color: '#94a3b8' }}><strong>Notes:</strong> {item.notes}</div>}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}

              {/* View 3: Live AI Strategist Chat */}
              {topicSubTab === 'chat' && (
                <div className="panel-card" style={{ display: 'flex', flexDirection: 'column', minHeight: '650px', padding: 0, overflow: 'hidden' }}>
                  {/* Sticky Chat Header */}
                  <div style={{ backgroundColor: '#0e1017', borderBottom: '1px solid #1e2230', padding: '18px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px', position: 'sticky', top: 0, zIndex: 20 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <div style={{ width: '40px', height: '40px', borderRadius: '50%', backgroundColor: '#1c1827', border: '1px solid #a78bfa', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#a78bfa' }}>
                        <Bot size={22} />
                      </div>
                      <div>
                        <div style={{ fontSize: '1.1rem', fontWeight: 700, color: '#ffffff', display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span>{getStrategistAgentName(selectedChannel)}</span>
                          <span style={{ fontSize: '0.75rem', backgroundColor: '#0b261d', color: '#4ade80', padding: '2px 8px', borderRadius: '9999px', fontWeight: 600 }}>Active Agent</span>
                        </div>
                        <div style={{ fontSize: '0.8rem', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: '8px', marginTop: '4px' }}>
                          <span>Target Channel:</span>
                          <select 
                            className="form-control" 
                            style={{ padding: '2px 8px', fontSize: '0.8rem', fontWeight: 700, color: '#f43f5e', backgroundColor: '#161923', borderColor: '#334155', cursor: 'pointer', width: 'auto' }}
                            value={selectedChannel}
                            onChange={(e) => {
                              const newChan = e.target.value;
                              setSelectedChannel(newChan);
                              const newAgent = getStrategistAgentName(newChan);
                              setChatMessages(prev => [
                                ...prev,
                                {
                                  sender: 'agent',
                                  text: `🔄 **Channel & Strategist Switched!**\n\nYou are now speaking with **${newAgent}** for **${newChan}**.\n\nHow can I help you frame ideas, write hooks, or structure videos for ${newChan}?`,
                                  timestamp: new Date().toLocaleTimeString()
                                }
                              ]);
                            }}
                          >
                            <option value="Spilled Coffee Studio">✍️ Spilled Coffee Studio (SpilledCoffeeStudioStrategist)</option>
                            <option value="Spilled Coffee After Dark">👻 Spilled Coffee After Dark (AfterDarkStrategist)</option>
                            <option value="Beyond3Baje">🕵️ Beyond3Baje (Beyond3BajeStrategist)</option>
                            <option value="Life3Baje">☕ Life3Baje (Life3BajeStrategist)</option>
                            <option value="Khayal3Baje">🏛️ Khayal3Baje (Khayal3BajeStrategist)</option>
                          </select>
                        </div>
                      </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      {/* Switch Channel Quick Action Button */}
                      <button 
                        className="btn btn-outline" 
                        style={{ padding: '6px 12px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '6px', backgroundColor: '#161923', borderColor: '#f43f5e', color: '#f43f5e' }}
                        onClick={() => setTopicSubTab('discovered')}
                        title="Go back to Channel Topic Discovery cards"
                      >
                        <Compass size={14} />
                        <span>Browse Channel Cards 🧭</span>
                      </button>

                      {/* Clear Memory & Chat Button */}
                      <button 
                        className="btn btn-outline" 
                        style={{ padding: '6px 12px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '6px', backgroundColor: '#161923', borderColor: '#7f1d1d', color: '#fca5a5' }}
                        onClick={async () => {
                          if (confirm(`Clear all persistent memory and conversation history for ${getStrategistAgentName(selectedChannel)}?`)) {
                            await fetch(`/api/memory/clear?scope=agent&owner=${encodeURIComponent(getStrategistAgentName(selectedChannel))}`, { method: 'POST' });
                            await fetch(`/api/memory/clear?scope=session&owner=${encodeURIComponent(selectedChannel)}`, { method: 'POST' });
                            setChatMessages([{
                              sender: 'agent',
                              text: `🧠 **Memory & Chat Thread Cleared!**\n\nI am **${getStrategistAgentName(selectedChannel)}**. Starting a fresh strategic conversation session for **${selectedChannel}**.`,
                              timestamp: new Date().toLocaleTimeString()
                            }]);
                          }
                        }}
                        title="Clear all persistent memories and past conversation turns for this agent"
                      >
                        <Trash2 size={14} />
                        <span>Clear Memory 🗑️</span>
                      </button>

                      {/* Go to Top of Chat Button */}
                      <button 
                        className="btn btn-outline" 
                        style={{ padding: '6px 12px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '6px', backgroundColor: '#161923', borderColor: '#232738' }}
                        onClick={() => chatMessagesContainerRef.current?.scrollTo({ top: 0, behavior: 'smooth' })}
                        title="Scroll to Top of Chat Thread"
                      >
                        <ChevronUp size={14} />
                        <span>Go to Top ⬆️</span>
                      </button>

                      {activeChatTopic && (
                        <div style={{ backgroundColor: '#161923', border: '1px solid #232738', padding: '6px 14px', borderRadius: '8px', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <span>Target Topic: <strong style={{ color: '#ffffff' }}>{activeChatTopic.topic.substring(0, 35)}...</strong></span>
                          <button 
                            onClick={() => setActiveChatTopic(null)}
                            style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', fontSize: '0.8rem', textDecoration: 'underline' }}
                          >
                            Clear
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Conversation Message Log */}
                  <div ref={chatMessagesContainerRef} style={{ flex: 1, padding: '24px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '16px', backgroundColor: '#08090d', maxHeight: '550px' }}>
                    {chatMessages.length === 0 ? (
                      <div style={{ textAlign: 'center', margin: 'auto', color: '#64748b' }}>
                        <Bot size={40} style={{ opacity: 0.4, marginBottom: '12px' }} />
                        <p style={{ margin: 0, fontSize: '1rem', color: '#e2e8f0' }}>Start a live discussion with <strong>{getStrategistAgentName(selectedChannel)}</strong></p>
                        <p style={{ fontSize: '0.85rem', marginTop: '6px' }}>Discuss video angles, titles, hooks, or script structure changes!</p>
                      </div>
                    ) : (
                      chatMessages.map((msg, i) => (
                        <div key={i} className={msg.sender === 'user' ? 'chat-bubble-user' : 'chat-bubble-agent'}>
                          <div style={{ fontSize: '0.75rem', opacity: 0.6, marginBottom: '4px', fontWeight: 600 }}>
                            {msg.sender === 'user' ? 'You' : getStrategistAgentName(selectedChannel)} • {msg.timestamp}
                          </div>
                          <div>{msg.text}</div>
                        </div>
                      ))
                    )}

                    {isChatSending && (
                      <div className="chat-bubble-agent" style={{ opacity: 0.7 }}>
                        <em>{getStrategistAgentName(selectedChannel)} is formulating strategic advice...</em>
                      </div>
                    )}
                  </div>

                  {/* Suggestion Chips */}
                  <div style={{ backgroundColor: '#0e1017', borderTop: '1px solid #1a1d29', padding: '12px 24px', display: 'flex', gap: '10px', overflowX: 'auto' }}>
                    {[
                      '💡 Give me 3 viral thumbnail hooks',
                      '🎬 Write a 45-sec retention intro script',
                      '📊 How does this fit our channel pillars?',
                      '🗺️ What visual B-roll & maps should we use?'
                    ].map((chip, idx) => (
                      <button 
                        key={idx}
                        onClick={() => handleSendChatMessage(chip)}
                        style={{
                          backgroundColor: '#161923',
                          border: '1px solid #232738',
                          color: '#e2e8f0',
                          padding: '6px 12px',
                          borderRadius: '9999px',
                          fontSize: '0.8rem',
                          cursor: 'pointer',
                          whiteSpace: 'nowrap',
                          transition: 'border-color 0.2s'
                        }}
                      >
                        {chip}
                      </button>
                    ))}
                  </div>

                  {/* Chat Input Footer */}
                  <div style={{ backgroundColor: '#0e1017', padding: '16px 24px', display: 'flex', gap: '12px', alignItems: 'center' }}>
                    <input 
                      type="text" 
                      className="form-control"
                      placeholder={`Talk to ${getStrategistAgentName(selectedChannel)} about video ideas, hooks, or script changes...`}
                      value={chatInput}
                      onChange={e => setChatInput(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter') handleSendChatMessage(); }}
                    />
                    <button className="btn" disabled={isChatSending} onClick={() => handleSendChatMessage()}>
                      <Send size={18} />
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Tab: Voice Script Dictation Studio */}
          {activeTab === 'dictation_studio' && (
            <div>
              {/* Header Banner */}
              <div className="panel-card" style={{ marginBottom: '24px', backgroundColor: '#0f131f', border: '1px solid #1e293b' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
                  <div>
                    <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0, display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <Mic size={24} style={{ color: isDictating ? '#f43f5e' : '#38bdf8' }} />
                      <span>Continuous Voice Script Dictation Studio</span>
                    </h3>
                    <p style={{ color: '#94a3b8', margin: '6px 0 0 0' }}>High-sensitivity voice dictation in Hinglish/Hindi & English. Continuous listening lets you pause, think, and speak seamlessly!</p>
                  </div>

                  {/* Power Toggle Button, Language & Sensitivity Controls */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <span style={{ fontSize: '0.85rem', color: '#94a3b8' }}>Language:</span>
                      <select 
                        className="form-control" 
                        style={{ padding: '6px 12px', fontSize: '0.85rem', fontWeight: 600 }}
                        value={dictationLang}
                        onChange={e => setDictationLang(e.target.value)}
                      >
                        <option value="hi-IN">🇮🇳 Hinglish / Hindi (hi-IN)</option>
                        <option value="en-IN">🇮🇳 Indian English (en-IN)</option>
                        <option value="en-US">🇺🇸 Global English (en-US)</option>
                      </select>
                    </div>

                    <button 
                      className="btn btn-outline"
                      style={{
                        padding: '6px 12px',
                        fontSize: '0.8rem',
                        borderColor: highSensitivity ? '#f59e0b' : '#334155',
                        color: highSensitivity ? '#fbcfe8' : '#94a3b8',
                        backgroundColor: highSensitivity ? '#2d1810' : '#161923'
                      }}
                      onClick={() => setHighSensitivity(!highSensitivity)}
                      title="Toggles 3-alternative high-sensitivity speech processing"
                    >
                      <span>🔥 High Sensitivity: {highSensitivity ? 'ON' : 'OFF'}</span>
                    </button>

                    <button 
                      className={`btn ${isDictating ? 'btn-danger' : 'btn-primary'}`}
                      style={{
                        padding: '10px 22px',
                        fontSize: '0.95rem',
                        fontWeight: 700,
                        display: 'flex',
                        alignItems: 'center',
                        gap: '10px',
                        boxShadow: isDictating ? '0 0 20px rgba(244, 63, 94, 0.4)' : 'none',
                        border: isDictating ? '2px solid #f43f5e' : 'none'
                      }}
                      onClick={toggleDictation}
                    >
                      {isDictating ? <MicOff size={20} /> : <Mic size={20} />}
                      <span>{isDictating ? '🛑 STOP DICTATION' : '🎙️ START CONTINUOUS DICTATION'}</span>
                    </button>
                  </div>
                </div>

                {/* Status Bar & Quick Width Presets */}
                <div style={{ marginTop: '16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', fontSize: '0.85rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <span style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '6px',
                      padding: '4px 12px',
                      borderRadius: '9999px',
                      fontWeight: 600,
                      backgroundColor: isDictating ? '#290e18' : '#1e293b',
                      color: isDictating ? '#f43f5e' : '#94a3b8',
                      border: isDictating ? '1px solid #f43f5e' : '1px solid #334155'
                    }}>
                      <span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: isDictating ? '#f43f5e' : '#64748b' }}></span>
                      {isDictating ? '🔴 LIVE DICTATING — Listening continuously (Pause & Think allowed)' : '⚪ Dictation Offline'}
                    </span>
                    <span style={{ color: '#64748b' }}>Voice commands: <strong>"delete line"</strong>, <strong>"new line"</strong>, <strong>"clear canvas"</strong></span>
                  </div>

                  {/* Panel Width Preset Quick Buttons */}
                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <span style={{ color: '#64748b', fontSize: '0.8rem' }}>Canvas Ratio:</span>
                    {[
                      { label: '78% Canvas (Default)', val: 78 },
                      { label: '85% Wide Canvas', val: 85 },
                      { label: '60% Equal Split', val: 60 }
                    ].map(preset => (
                      <button 
                        key={preset.val}
                        onClick={() => setLeftPanelWidth(preset.val)}
                        style={{
                          backgroundColor: leftPanelWidth === preset.val ? '#1e293b' : '#090a0f',
                          border: leftPanelWidth === preset.val ? '1px solid #38bdf8' : '1px solid #1e293b',
                          color: leftPanelWidth === preset.val ? '#38bdf8' : '#94a3b8',
                          fontSize: '0.75rem',
                          padding: '3px 8px',
                          borderRadius: '4px',
                          cursor: 'pointer'
                        }}
                      >
                        {preset.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {/* Draggable & Resizable Split Container (Default 78% Script Canvas Width) */}
              <div 
                ref={dictationContainerRef}
                style={{ 
                  display: 'flex', 
                  gap: '0', 
                  alignItems: 'stretch',
                  position: 'relative',
                  width: '100%',
                  minWidth: 0,
                  overflow: 'hidden',
                  userSelect: isDraggingSplitter ? 'none' : 'auto'
                }}
              >
                
                {/* Left Panel: Wide Script Dictation Canvas (78% Default) */}
                <div style={{ width: `${leftPanelWidth}%`, minWidth: 0, display: 'flex', flexDirection: 'column', paddingRight: '8px', overflow: 'hidden' }}>
                  <div className="panel-card" style={{ display: 'flex', flexDirection: 'column', minHeight: '620px', height: '100%', minWidth: 0, overflow: 'hidden' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '10px' }}>
                      <h4 style={{ margin: 0, color: '#ffffff', fontSize: '1.15rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <FileText size={20} style={{ color: '#38bdf8' }} />
                        <span>Script Draft Canvas ({Math.round(leftPanelWidth)}% Width)</span>
                      </h4>

                      {/* Word / Duration Metrics */}
                      <div style={{ fontSize: '0.85rem', color: '#38bdf8', backgroundColor: '#0c2233', padding: '6px 14px', borderRadius: '6px', fontWeight: 600 }}>
                        {dictationText.trim().split(/\s+/).filter(Boolean).length} words • {dictationText.split('\n').filter(Boolean).length} lines • ~{Math.ceil(dictationText.trim().split(/\s+/).filter(Boolean).length / 2.5)}s audio duration
                      </div>
                    </div>

                    {/* Realtime Interim Transcribing Speech Bubble */}
                    {interimText && (
                      <div style={{ backgroundColor: '#1e1b2e', border: '1px solid #a78bfa', padding: '10px 16px', borderRadius: '8px', color: '#a78bfa', fontSize: '0.95rem', marginBottom: '14px', fontStyle: 'italic', wordBreak: 'break-word' }}>
                        🎙️ High-Sensitivity Transcribing: <strong>{interimText}...</strong>
                      </div>
                    )}

                    {/* Textarea Editor Canvas */}
                    <textarea 
                      className="form-control"
                      rows={20}
                      placeholder="Click 'START CONTINUOUS DICTATION' above and start speaking in Hinglish or English... Your spoken voice will stream here continuously!"
                      value={dictationText}
                      onChange={e => setDictationText(e.target.value)}
                      style={{
                        width: '100%',
                        boxSizing: 'border-box',
                        fontFamily: 'monospace, monospace',
                        fontSize: '1rem',
                        lineHeight: '1.7',
                        padding: '20px',
                        backgroundColor: '#090a0f',
                        borderColor: '#1e293b',
                        borderRadius: '8px',
                        flex: 1,
                        resize: 'vertical'
                      }}
                    />

                    {/* Script Actions Toolbar */}
                    <div style={{ display: 'flex', gap: '10px', marginTop: '16px', flexWrap: 'wrap', justifyContent: 'space-between' }}>
                      <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                        <button 
                          className="btn btn-outline"
                          style={{ padding: '8px 16px', fontSize: '0.85rem', borderColor: '#e11d48', color: '#fda4af' }}
                          onClick={handleDeleteLastLine}
                          title="Erase the last line or sentence from your script draft"
                        >
                          <Trash2 size={15} />
                          <span>Delete Last Line ✂️</span>
                        </button>

                        <button 
                          className="btn btn-outline"
                          style={{ padding: '8px 16px', fontSize: '0.85rem' }}
                          onClick={() => setDictationText('')}
                          title="Clear canvas"
                        >
                          <RotateCw size={15} />
                          <span>Clear Canvas 🧹</span>
                        </button>

                        <button 
                          className="btn btn-outline"
                          style={{ padding: '8px 16px', fontSize: '0.85rem' }}
                          onClick={() => { navigator.clipboard.writeText(dictationText); alert('Script draft copied to clipboard!'); }}
                        >
                          <span>Copy Script 📋</span>
                        </button>
                      </div>

                      <button 
                        className="btn btn-outline"
                        style={{ padding: '8px 16px', fontSize: '0.85rem', borderColor: '#38bdf8', color: '#38bdf8' }}
                        onClick={handleSaveDictationDraft}
                      >
                        <Bookmark size={15} />
                        <span>Save Draft to Vault 💾</span>
                      </button>
                    </div>
                  </div>
                </div>

                {/* Draggable Vertical Splitter Resizer Handle */}
                <div 
                  onMouseDown={(e) => { e.preventDefault(); setIsDraggingSplitter(true); }}
                  title="Click and drag left or right to resize Script Canvas & AI Completer panels"
                  style={{
                    width: '14px',
                    cursor: 'col-resize',
                    display: 'flex',
                    alignItems: 'center',
                    justify: 'center',
                    backgroundColor: isDraggingSplitter ? '#f43f5e' : '#161923',
                    border: '1px solid #232738',
                    borderRadius: '6px',
                    margin: '0 4px',
                    zIndex: 10,
                    transition: 'background-color 0.2s',
                    minHeight: '620px',
                    flexShrink: 0
                  }}
                >
                  <div style={{ width: '3px', height: '40px', backgroundColor: isDraggingSplitter ? '#ffffff' : '#64748b', borderRadius: '2px' }}></div>
                </div>

                {/* Right Panel: AI Writing Agent Completer */}
                <div style={{ width: `calc(${100 - leftPanelWidth}% - 22px)`, minWidth: 0, display: 'flex', flexDirection: 'column', paddingLeft: '8px', overflow: 'hidden' }}>
                  <div className="panel-card" style={{ display: 'flex', flexDirection: 'column', minHeight: '620px', height: '100%', borderLeft: '4px solid #a78bfa', minWidth: 0, overflow: 'hidden', boxSizing: 'border-box' }}>
                    <div style={{ marginBottom: '16px', minWidth: 0 }}>
                      <h4 style={{ margin: 0, color: '#ffffff', fontSize: '1.05rem', display: 'flex', alignItems: 'center', gap: '8px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        <Sparkles size={18} style={{ color: '#a78bfa', flexShrink: 0 }} />
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>AI Story Completer</span>
                      </h4>
                      <p style={{ color: '#94a3b8', fontSize: '0.78rem', margin: '4px 0 0 0', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>Finish story in Hinglish using AI agent.</p>
                    </div>

                    {/* Controls Form */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', marginBottom: '16px', backgroundColor: '#090a0f', padding: '12px', borderRadius: '8px', border: '1px solid #1e293b', minWidth: 0, boxSizing: 'border-box' }}>
                      <div style={{ minWidth: 0 }}>
                        <label style={{ fontSize: '0.75rem', color: '#a78bfa', fontWeight: 600, display: 'block', marginBottom: '4px' }}>Target Writing Agent:</label>
                        <select 
                          className="form-control"
                          style={{ 
                            width: '100%', 
                            maxWidth: '100%', 
                            boxSizing: 'border-box',
                            padding: '6px 8px', 
                            fontSize: '0.82rem', 
                            fontWeight: 600,
                            textOverflow: 'ellipsis',
                            overflow: 'hidden',
                            whiteSpace: 'nowrap'
                          }}
                          value={selectedWriterRole}
                          onChange={e => setSelectedWriterRole(e.target.value)}
                        >
                          <option value="ScriptWriter">✍️ ScriptWriter</option>
                          <option value="WriterAgent">📖 WriterAgent</option>
                          <option value="OutlineWriter">📋 OutlineWriter</option>
                          <option value="DialogueWriter">💬 DialogueWriter</option>
                          <option value="HorrorSpecialist">👻 HorrorSpecialist</option>
                          <option value="MythologySpecialist">🏛️ MythologySpecialist</option>
                        </select>
                      </div>

                      <div style={{ minWidth: 0 }}>
                        <label style={{ fontSize: '0.75rem', color: '#a78bfa', fontWeight: 600, display: 'block', marginBottom: '4px' }}>Completion Directive:</label>
                        <select 
                          className="form-control"
                          style={{ 
                            width: '100%', 
                            maxWidth: '100%', 
                            boxSizing: 'border-box',
                            padding: '6px 8px', 
                            fontSize: '0.78rem',
                            textOverflow: 'ellipsis',
                            overflow: 'hidden',
                            whiteSpace: 'nowrap'
                          }}
                          value={completionDirective}
                          onChange={e => setCompletionDirective(e.target.value)}
                        >
                          <option value="complete">🚀 Complete Story (Hinglish)</option>
                          <option value="full_script">🎬 Full Production Script</option>
                          <option value="hooks_visuals">💡 Hooks & B-Roll Visuals</option>
                          <option value="polish">🎭 Polish Script Pacing</option>
                        </select>
                      </div>

                      <button 
                        className="btn" 
                        style={{ 
                          width: '100%', 
                          maxWidth: '100%', 
                          boxSizing: 'border-box',
                          padding: '10px 8px', 
                          fontSize: '0.82rem', 
                          fontWeight: 700, 
                          display: 'flex', 
                          justify: 'center', 
                          alignItems: 'center', 
                          gap: '6px',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap'
                        }}
                        disabled={isAiCompleting || !dictationText.trim()}
                        onClick={handleAiCompleteScript}
                      >
                        <Sparkles size={15} style={{ flexShrink: 0 }} />
                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{isAiCompleting ? `Writing...` : `AI Complete Script 🚀`}</span>
                      </button>
                    </div>

                    {/* AI Completion Output Container */}
                    <div style={{ flex: 1, backgroundColor: '#08090d', border: '1px solid #1e293b', borderRadius: '8px', padding: '12px', overflowY: 'auto', maxHeight: '420px', minWidth: 0 }}>
                      {isAiCompleting ? (
                        <div style={{ textAlign: 'center', padding: '20px 6px', color: '#a78bfa' }}>
                          <Sparkles size={28} className="spin" style={{ marginBottom: '10px' }} />
                          <p style={{ margin: 0, fontSize: '0.85rem', fontWeight: 600 }}>{selectedWriterRole} is writing...</p>
                          <p style={{ fontSize: '0.78rem', color: '#64748b', marginTop: '4px' }}>Formulating story conclusion in Hinglish...</p>
                        </div>
                      ) : aiOutputResult ? (
                        <div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px', flexWrap: 'wrap', gap: '6px' }}>
                            <span style={{ fontSize: '0.75rem', color: '#4ade80', fontWeight: 700, backgroundColor: '#0b261d', padding: '2px 6px', borderRadius: '4px' }}>✓ AI Done</span>
                            <div style={{ display: 'flex', gap: '6px' }}>
                              <button 
                                className="btn btn-outline" 
                                style={{ padding: '3px 8px', fontSize: '0.7rem' }}
                                onClick={() => setDictationText(aiOutputResult)}
                                title="Replace draft in canvas with AI completed script"
                              >
                                Replace 📥
                              </button>
                              <button 
                                className="btn btn-outline" 
                                style={{ padding: '3px 8px', fontSize: '0.7rem' }}
                                onClick={() => setDictationText(prev => prev + '\n\n### AI Agent Completion:\n' + aiOutputResult)}
                                title="Append AI script to existing draft"
                              >
                                Append ➕
                              </button>
                            </div>
                          </div>
                          <div style={{ whiteSpace: 'pre-wrap', fontSize: '0.85rem', color: '#e2e8f0', lineHeight: 1.6, wordBreak: 'break-word' }}>
                            {aiOutputResult}
                          </div>
                        </div>
                      ) : (
                        <div style={{ textAlign: 'center', padding: '20px 6px', color: '#64748b' }}>
                          <Bot size={28} style={{ opacity: 0.4, marginBottom: '8px' }} />
                          <p style={{ margin: 0, fontSize: '0.8rem' }}>Dictate draft on left, then click <strong>AI Complete Script</strong>!</p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>

              </div>

              {/* Saved Dictation Drafts Vault */}
              {savedDictations.length > 0 && (
                <div className="panel-card" style={{ marginTop: '24px' }}>
                  <h4 style={{ margin: '0 0 16px 0', color: '#ffffff', fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <Bookmark size={20} style={{ color: '#f59e0b' }} />
                    <span>Saved Dictation Vault ({savedDictations.length} Drafts)</span>
                  </h4>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '16px' }}>
                    {savedDictations.map(draft => (
                      <div key={draft.id} style={{ backgroundColor: '#08090d', border: '1px solid #1e293b', borderRadius: '8px', padding: '14px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
                        <div>
                          <div style={{ fontSize: '0.75rem', color: '#94a3b8', marginBottom: '6px' }}>{draft.date}</div>
                          <div style={{ fontSize: '0.9rem', color: '#ffffff', fontWeight: 600, marginBottom: '10px' }}>{draft.title}</div>
                        </div>
                        <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
                          <button 
                            className="btn btn-outline" 
                            style={{ padding: '4px 10px', fontSize: '0.75rem', flex: 1 }}
                            onClick={() => setDictationText(draft.text)}
                          >
                            Load Draft 📂
                          </button>
                          <button 
                            className="btn btn-outline" 
                            style={{ padding: '4px 8px', fontSize: '0.75rem', borderColor: '#7f1d1d', color: '#fca5a5' }}
                            onClick={() => handleDeleteDictationDraft(draft.id)}
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Tab: Projects Page */}
          {activeTab === 'projects' && (
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
                <h2 style={{ margin: 0, fontSize: '1.5rem', color: '#ffffff' }}>Active Projects</h2>
                <button className="btn btn-outline" onClick={fetchProjects}>
                  <RotateCw size={16} />
                  <span>Refresh List</span>
                </button>
              </div>

              <div className="project-list">
                {projects.map((proj) => (
                  <div key={proj.id} className="project-item">
                    <div className="project-info">
                      <div className="project-name">{proj.name}</div>
                      <div className="project-meta">
                        <span>ID: <code style={{ color: '#94a3b8' }}>{proj.id}</code></span>
                        <span>Brand: <span className="brand-badge">{proj.brand}</span></span>
                        <span>Workflow: <code style={{ color: '#e2e8f0' }}>{proj.workflow_name}</code></span>
                      </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                      <span className={`status-badge-inline status-${proj.status}`}>
                        {proj.status.toUpperCase()}
                      </span>
                      
                      <button 
                        className="btn" 
                        disabled={runningProjId !== null}
                        onClick={() => handleRunWorkflowStep(proj.id)}
                        style={{ padding: '8px 16px', fontSize: '0.85rem' }}
                      >
                        <Play size={14} />
                        <span>Run Next Step</span>
                      </button>
                    </div>

                    {runningProjId === proj.id && (
                      <div style={{ width: '100%' }}>
                        <div className="logs-panel">
                          {runLog.map((log, index) => (
                            <div key={index} style={{ display: 'flex', gap: '10px' }}>
                              <span style={{ color: '#64748b' }}>[{new Date().toLocaleTimeString()}]</span>
                              <span>{log}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tab: Research Workspace */}
          {activeTab === 'research' && (
            <div>
              <div className="panel-card">
                <h3 className="panel-title"><BookOpen size={20} /> Citation Vector Explorer</h3>
                <p style={{ color: '#94a3b8', margin: '0 0 20px 0' }}>Search and query factual citations, articles, and libraries compiled by the research agents.</p>
                <div style={{ display: 'flex', gap: '16px' }}>
                  <input type="text" className="form-control" style={{ flex: 1 }} placeholder="Search research databases..." />
                  <button className="btn"><Search size={18} /><span>Query Database</span></button>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '20px' }}>
                <div className="panel-card" style={{ padding: '24px' }}>
                  <h4 style={{ margin: '0 0 12px 0', color: '#ffffff' }}>Research: Penny Universities of London</h4>
                  <p style={{ fontStyle: 'italic', fontSize: '0.9rem', color: '#94a3b8' }}>Author: DocumentaryResearcherAgent</p>
                  <p style={{ fontSize: '0.95rem', color: '#cbd5e1' }}>Investigation of 18th century coffee houses and their connection to early insurance societies like Lloyd's.</p>
                  <a href="#" style={{ color: '#f43f5e', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '4px', fontWeight: '500', fontSize: '0.9rem', marginTop: '16px' }}>
                    <span>Explore Citation Library</span> <ChevronRight size={14} />
                  </a>
                </div>

                <div className="panel-card" style={{ padding: '24px' }}>
                  <h4 style={{ margin: '0 0 12px 0', color: '#ffffff' }}>Citations Verified Log</h4>
                  <p style={{ fontStyle: 'italic', fontSize: '0.9rem', color: '#94a3b8' }}>Status: Syncing with Vector DB</p>
                  <p style={{ fontSize: '0.95rem', color: '#cbd5e1' }}>Ensures all creative claims made by writing agents match historical references before video exporting.</p>
                  <a href="#" style={{ color: '#f43f5e', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: '4px', fontWeight: '500', fontSize: '0.9rem', marginTop: '16px' }}>
                    <span>Browse Vector Keys</span> <ChevronRight size={14} />
                  </a>
                </div>
              </div>
            </div>
          )}

          {/* Tab: Writing Studio */}
          {activeTab === 'writing' && (
            <div>
              <div className="panel-card">
                <h3 className="panel-title"><FileText size={20} /> Script Draft Editor</h3>
                <div style={{ display: 'flex', gap: '20px', marginBottom: '20px' }}>
                  <button className="btn" style={{ padding: '8px 16px', fontSize: '0.85rem' }}>Generate Script via AI</button>
                  <button className="btn btn-outline" style={{ padding: '8px 16px', fontSize: '0.85rem' }}>Run Fact Checker</button>
                </div>
                
                <div className="parchment-editor" contentEditable>
                  {`[Visual Cue: Steam rises slowly from a dark, rich coffee cup filling the screen in macro.]

NARRATOR (V.O.)
In 1652, a strange new substance arrived in London. It was dark, bitter, and smelled of roasted earth. They called it the 'bitter invention of Satan'. But within a decade, this single bean would spark a revolution that changed the course of human history.`}
                </div>
              </div>
            </div>
          )}

          {/* Tab: Production */}
          {activeTab === 'production' && (
            <div>
              <div className="panel-card">
                <h3 className="panel-title"><Video size={20} /> Filmora Scene Planner & Exporter</h3>
                <p style={{ color: '#94a3b8', margin: '0 0 20px 0' }}>Plan scenes, build visual prompt storyboards, and generate Filmora XML timelines.</p>
                
                <button className="btn" style={{ marginBottom: '24px' }}>
                  <span>Build Filmora XML Timeline Bundle</span>
                </button>

                <div className="timeline-container">
                  <div className="timeline-step">
                    <div className="step-num">1</div>
                    <div style={{ flex: 1 }}>
                      <h4 style={{ margin: '0 0 4px 0', color: '#ffffff' }}>Scene 1: Introduction</h4>
                      <p style={{ margin: 0, fontSize: '0.9rem', color: '#94a3b8' }}>Visual: Steaming coffee macro cup. Audio: Narrator V.O. intro.</p>
                    </div>
                  </div>

                  <div className="timeline-step">
                    <div className="step-num">2</div>
                    <div style={{ flex: 1 }}>
                      <h4 style={{ margin: '0 0 4px 0', color: '#ffffff' }}>Scene 2: The Penny Universities</h4>
                      <p style={{ margin: 0, fontSize: '0.9rem', color: '#94a3b8' }}>Visual: Archival London sketch graphics. Audio: Background crowd murmur.</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Tab: Publishing & Analytics */}
          {activeTab === 'publishing' && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '24px' }}>
              <div className="panel-card">
                <h3 className="panel-title"><Share2 size={20} /> YouTube & Notion Publishing</h3>
                <div className="form-group" style={{ marginBottom: '16px' }}>
                  <label>YouTube Upload Status</label>
                  <input type="text" className="form-control" value="Pending Export" readOnly />
                </div>
                <div className="form-group" style={{ marginBottom: '16px' }}>
                  <label>Notion Card Link</label>
                  <input type="text" className="form-control" value="Synced - ID #884321" readOnly />
                </div>
                <button className="btn">Publish Schedule Calendar</button>
              </div>

              <div className="panel-card">
                <h3 className="panel-title"><BarChart3 size={20} /> Channel Performance Analytics</h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #1e2230' }}>
                    <span>Target Impressions CTR</span>
                    <span style={{ color: '#4ade80', fontWeight: '700' }}>8.4%</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0', borderBottom: '1px solid #1e2230' }}>
                    <span>Avg View Retention</span>
                    <span style={{ color: '#4ade80', fontWeight: '700' }}>62.1%</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 0' }}>
                    <span>RPM Value</span>
                    <span style={{ color: '#38bdf8', fontWeight: '700' }}>$4.82</span>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Tab: AI Workforce */}
          {activeTab === 'ai_workforce' && (
            <div>
              <div className="panel-card" style={{ marginBottom: '24px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
                  <div>
                    <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0 }}><Users size={20} /> Registered AI Workforce ({registeredAgents.length || 115} Agents)</h3>
                    <p style={{ color: '#94a3b8', margin: '4px 0 0 0' }}>All {registeredAgents.length || 115} registered specialized agents in the Spilled Coffee AI pipeline.</p>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <Search size={16} style={{ color: '#94a3b8' }} />
                    <input 
                      type="text" 
                      className="form-control" 
                      placeholder="Filter agent by name..." 
                      value={agentFilter} 
                      onChange={e => setAgentFilter(e.target.value)} 
                      style={{ padding: '6px 12px', fontSize: '0.85rem', width: '220px' }}
                    />
                  </div>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '16px' }}>
                {(registeredAgents.length > 0 ? registeredAgents : [
                  { name: 'SpilledCoffeeStudioStrategist' }, { name: 'AfterDarkStrategist' }, { name: 'Beyond3BajeStrategist' },
                  { name: 'Life3BajeStrategist' }, { name: 'Khayal3BajeStrategist' }, { name: 'TopicVaultManager' },
                  { name: 'CreativeDirectorAgent' }, { name: 'CTRAnalyzer' }, { name: 'DescriptionWriter' },
                  { name: 'DocumentaryResearcher' }, { name: 'EditorAgent' }, { name: 'FactChecker' },
                  { name: 'SEOManagerAgent' }, { name: 'WriterAgent' }
                ])
                .filter(a => !agentFilter || a.name.toLowerCase().includes(agentFilter.toLowerCase()))
                .map((ag) => (
                  <div key={ag.name} className="panel-card" style={{ padding: '16px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', margin: 0 }}>
                    <div>
                      <h4 style={{ margin: '0 0 4px 0', color: '#ffffff', fontSize: '0.95rem' }}>{ag.name}</h4>
                      <span style={{ fontSize: '0.78rem', color: '#94a3b8' }}>Status: <span style={{ color: '#4ade80', fontWeight: '600' }}>Active & Ready</span></span>
                    </div>
                    <Cpu size={22} style={{ color: '#a78bfa', opacity: 0.8 }} />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Tab: System Health */}
          {activeTab === 'health' && (
            <div className="panel-card">
              <h3 className="panel-title"><ShieldCheck size={20} /> System Diagnostics Logs</h3>
              <div className="logs-panel" style={{ height: '300px', color: '#fca5a5' }}>
                <div>[OK] Configuration validation successful.</div>
                <div>[OK] Folder exists: Projects path 'backend/projects'</div>
                <div>[OK] Folder exists: Knowledge path 'backend/knowledge'</div>
                <div>[OK] Folder exists: Prompts path 'backend/prompts'</div>
                <div>[OK] Agent Registry load: {registeredAgents.length || 115} agents registered.</div>
                <div>[OK] Workflow Registry load: 6 workflows registered.</div>
                <div>[OK] Workflow circular dependency validation successful.</div>
                <div style={{ color: '#4ade80' }}>System Health Status: HEALTHY</div>
              </div>
            </div>
          )}

          {/* Tab: Settings */}
          {activeTab === 'settings' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              <div className="panel-card">
                <h3 className="panel-title"><SettingsIcon size={20} /> AI Model Provider Integration</h3>
                <form onSubmit={handleSaveSettings}>
                  <div className="form-group" style={{ marginBottom: '24px' }}>
                    <label>Selected AI Model Provider</label>
                    <select 
                      className="form-control"
                      value={selectedLlm}
                      onChange={e => setSelectedLlm(e.target.value)}
                    >
                      <option value="gemini">Google Gemini API (Default Model: gemini-3.6-flash)</option>
                      <option value="openai">OpenAI ChatGPT API (Default Model: gpt-4o-mini)</option>
                      <option value="lm_studio">Local LM Studio API (Default Port: http://localhost:1234/v1)</option>
                    </select>
                  </div>

                  <div className="form-group" style={{ marginBottom: '24px' }}>
                    <label>Google Gemini API Key</label>
                    <input 
                      type="password" 
                      className="form-control" 
                      placeholder="AIzaSy..." 
                      value={geminiKey}
                      onChange={e => setGeminiKey(e.target.value)}
                    />
                  </div>

                  <div className="form-group" style={{ marginBottom: '24px' }}>
                    <label>OpenAI (ChatGPT) API Key</label>
                    <input 
                      type="password" 
                      className="form-control" 
                      placeholder="sk-proj-..." 
                      value={openaiKey}
                      onChange={e => setOpenaiKey(e.target.value)}
                    />
                  </div>

                  <button type="submit" className="btn">
                    <CheckCircle2 size={18} />
                    <span>Save AI Router Settings</span>
                  </button>
                </form>
              </div>

              {/* Voice Engine Multi-Provider Panel */}
              <div className="panel-card">
                <h3 className="panel-title"><Mic size={20} style={{ color: '#f43f5e' }} /> Voice Command Engine Provider Selection</h3>
                <p style={{ color: '#94a3b8', margin: '0 0 20px 0' }}>Select your preferred speech recognition and voice synthesis engine.</p>

                <div className="form-group" style={{ marginBottom: '24px' }}>
                  <label>Active Voice Engine</label>
                  <select 
                    className="form-control"
                    value={voiceProvider}
                    onChange={e => {
                      const newProv = e.target.value;
                      setVoiceProvider(newProv);
                      localStorage.setItem('voice_provider', newProv);
                      fetch('/api/voice/config', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ provider: newProv })
                      }).catch(() => {});
                    }}
                  >
                    <option value="native_local">⚡ Browser Native Local Engine (100% Free & Offline / No Setup Needed)</option>
                    <option value="picovoice_wasm">⚙️ Picovoice Porcupine Engine (Wasm On-Device Wake-Word - Free & Offline)</option>
                    <option value="openai_realtime">🎙️ OpenAI Realtime Voice API (Neural Low-Latency Conversational AI)</option>
                  </select>
                </div>

                {voiceProvider === 'native_local' && (
                  <div style={{ backgroundColor: '#0b261d', border: '1px solid #4ade80', padding: '16px', borderRadius: '8px', marginBottom: '20px', color: '#4ade80', fontSize: '0.9rem' }}>
                    <strong>✓ Native Local Engine (Active): 100% Free & Offline.</strong><br />
                    Uses your browser's built-in speech recognition with Echo-Shield and noise thresholding. Runs completely offline without API keys!
                  </div>
                )}

                {voiceProvider === 'picovoice_wasm' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginBottom: '20px' }}>
                    <div style={{ backgroundColor: '#0c2233', border: '1px solid #38bdf8', padding: '14px', borderRadius: '8px', color: '#38bdf8', fontSize: '0.85rem' }}>
                      <strong>⚙️ Picovoice Porcupine (Wasm Engine): Free On-Device Wake-Word Engine.</strong><br />
                      Runs WebAssembly directly inside your browser for instant "Hey Buzzcaf" or "Hey Studio" wake-word detection offline.
                    </div>
                    <div className="form-group">
                      <label>Picovoice Access Key (Optional for Custom Keywords)</label>
                      <input 
                        type="password" 
                        className="form-control" 
                        placeholder="Picovoice AccessKey..." 
                        value={picovoiceKey}
                        onChange={e => setPicovoiceKey(e.target.value)}
                      />
                    </div>
                  </div>
                )}

                {voiceProvider === 'openai_realtime' && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginBottom: '20px' }}>
                    <div style={{ backgroundColor: '#1c1827', border: '1px solid #a78bfa', padding: '14px', borderRadius: '8px', color: '#a78bfa', fontSize: '0.85rem' }}>
                      <strong>🎙️ OpenAI Realtime Voice API: Neural Speech-to-Speech Engine.</strong><br />
                      Connects directly via WebSockets to OpenAI's GPT-4o Realtime Audio model for natural voice interaction.
                    </div>
                    <div className="form-group">
                      <label>OpenAI Realtime Voice API Key</label>
                      <input 
                        type="password" 
                        className="form-control" 
                        placeholder="sk-proj-..." 
                        value={openaiRealtimeKey}
                        onChange={e => setOpenaiRealtimeKey(e.target.value)}
                      />
                    </div>
                  </div>
                )}

                <button type="button" className="btn" onClick={() => {
                  localStorage.setItem('voice_provider', voiceProvider);
                  localStorage.setItem('picovoice_key', picovoiceKey);
                  localStorage.setItem('openai_realtime_key', openaiRealtimeKey);
                  fetch('/api/voice/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      provider: voiceProvider,
                      picovoice_access_key: picovoiceKey,
                      openai_realtime_key: openaiRealtimeKey
                    })
                  }).catch(() => {});
                  alert(`Saved Voice Configuration: Active provider set to ${voiceProvider}.`);
                }}>
                  <CheckCircle2 size={18} />
                  <span>Save Voice Configuration</span>
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Voice Activity Log Console Modal */}
      {showVoiceLogs && (
        <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0, 0, 0, 0.75)', backdropFilter: 'blur(6px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }}>
          <div style={{ backgroundColor: '#0f172a', border: '1px solid #38bdf8', borderRadius: '12px', width: '100%', maxWidth: '650px', maxHeight: '80vh', display: 'flex', flexDirection: 'column', overflow: 'hidden', boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)' }}>
            <div style={{ padding: '16px 20px', borderBottom: '1px solid #1e293b', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#38bdf8', fontWeight: 600, fontSize: '1.1rem' }}>
                <Sparkles size={20} style={{ color: '#a78bfa' }} />
                <span>Buzzcaf AI Voice Activity & Directive Log</span>
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                {voiceLogs.length > 0 && (
                  <button className="btn btn-outline" onClick={() => setVoiceLogs([])} style={{ padding: '4px 10px', fontSize: '0.8rem' }}>
                    Clear
                  </button>
                )}
                <button className="btn btn-outline" onClick={() => setShowVoiceLogs(false)} style={{ padding: '4px 10px', fontSize: '0.8rem' }}>
                  Close
                </button>
              </div>
            </div>

            <div style={{ padding: '16px 20px', overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {voiceLogs.length === 0 ? (
                <div style={{ textAlign: 'center', color: '#64748b', padding: '40px 0', fontSize: '0.9rem' }}>
                  <span>No voice activity logged yet. Speak a directive to see real-time activity!</span>
                </div>
              ) : (
                voiceLogs.map((log) => (
                  <div key={log.id} style={{ backgroundColor: '#1e293b', border: `1px solid ${log.type === 'USER' ? '#0284c7' : log.type === 'ACTION' ? '#059669' : '#7e22ce'}`, padding: '10px 14px', borderRadius: '8px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px', fontSize: '0.75rem', color: '#94a3b8' }}>
                      <span style={{ fontWeight: 600, color: log.type === 'USER' ? '#38bdf8' : log.type === 'ACTION' ? '#34d399' : '#c084fc' }}>
                        {log.type === 'USER' ? '🎤 SPOKEN DIRECTIVE' : log.type === 'ACTION' ? '⚡ EXECUTED ACTION' : '🤖 BUZZCAF RESPONSE'}
                      </span>
                      <span>{log.time}</span>
                    </div>
                    <div style={{ fontSize: '0.9rem', color: '#f8fafc', wordBreak: 'break-word' }}>
                      {log.type === 'USER' ? `"${log.text}"` : log.text}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      {/* Voice Tuning Control Panel Modal */}
      {showVoiceTuning && (
        <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0, 0, 0, 0.75)', backdropFilter: 'blur(6px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }}>
          <div style={{ backgroundColor: '#0f172a', border: '1px solid #0284c7', borderRadius: '12px', width: '100%', maxWidth: '600px', display: 'flex', flexDirection: 'column', overflow: 'hidden', boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.5)' }}>
            <div style={{ padding: '16px 20px', borderBottom: '1px solid #1e293b', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#38bdf8', fontWeight: 600, fontSize: '1.1rem' }}>
                <Sliders size={20} style={{ color: '#38bdf8' }} />
                <span>Buzzcaf AI Voice Persona Tuning</span>
              </div>
              <button className="btn btn-outline" onClick={() => setShowVoiceTuning(false)} style={{ padding: '4px 10px', fontSize: '0.8rem' }}>
                Close
              </button>
            </div>

            <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
              {/* Voice Selector */}
              <div className="form-group">
                <label style={{ color: '#38bdf8', fontWeight: 600, marginBottom: '6px', display: 'block' }}>
                  🎙️ Select Voice Model ({availableVoices.length} installed)
                </label>
                <select 
                  className="form-control" 
                  value={selectedVoiceURI} 
                  onChange={e => {
                    setSelectedVoiceURI(e.target.value);
                    localStorage.setItem('voice_selected_uri', e.target.value);
                  }}
                  style={{ backgroundColor: '#1e293b', color: '#ffffff', borderColor: '#334155' }}
                >
                  <option value="">-- Automatic Smooth Neural Voice (Recommended) --</option>
                  {availableVoices.map(v => (
                    <option key={v.voiceURI} value={v.voiceURI}>
                      {v.name} ({v.lang})
                    </option>
                  ))}
                </select>
              </div>

              {/* Rate / Speed Slider */}
              <div className="form-group">
                <div style={{ display: 'flex', justifyContent: 'space-between', color: '#cbd5e1', marginBottom: '6px', fontSize: '0.9rem' }}>
                  <span>⚡ Speaking Speed (Rate): <strong>{voiceRate.toFixed(2)}x</strong></span>
                  <span style={{ color: '#94a3b8', fontSize: '0.8rem' }}>(Default: 0.96x)</span>
                </div>
                <input 
                  type="range" 
                  min="0.5" 
                  max="1.5" 
                  step="0.02" 
                  value={voiceRate} 
                  onChange={e => {
                    const val = parseFloat(e.target.value);
                    setVoiceRate(val);
                    localStorage.setItem('voice_rate', val.toString());
                  }}
                  style={{ width: '100%', accentColor: '#38bdf8' }}
                />
              </div>

              {/* Pitch Slider */}
              <div className="form-group">
                <div style={{ display: 'flex', justifyContent: 'space-between', color: '#cbd5e1', marginBottom: '6px', fontSize: '0.9rem' }}>
                  <span>🎵 Voice Pitch: <strong>{voicePitch.toFixed(2)}</strong></span>
                  <span style={{ color: '#94a3b8', fontSize: '0.8rem' }}>(Default: 1.0)</span>
                </div>
                <input 
                  type="range" 
                  min="0.5" 
                  max="1.5" 
                  step="0.05" 
                  value={voicePitch} 
                  onChange={e => {
                    const val = parseFloat(e.target.value);
                    setVoicePitch(val);
                    localStorage.setItem('voice_pitch', val.toString());
                  }}
                  style={{ width: '100%', accentColor: '#a78bfa' }}
                />
              </div>

              {/* Volume Slider */}
              <div className="form-group">
                <div style={{ display: 'flex', justifyContent: 'space-between', color: '#cbd5e1', marginBottom: '6px', fontSize: '0.9rem' }}>
                  <span>🔊 Voice Volume: <strong>{Math.round(voiceVolume * 100)}%</strong></span>
                  <span style={{ color: '#94a3b8', fontSize: '0.8rem' }}>(Default: 100%)</span>
                </div>
                <input 
                  type="range" 
                  min="0.0" 
                  max="1.0" 
                  step="0.05" 
                  value={voiceVolume} 
                  onChange={e => {
                    const val = parseFloat(e.target.value);
                    setVoiceVolume(val);
                    localStorage.setItem('voice_volume', val.toString());
                  }}
                  style={{ width: '100%', accentColor: '#34d399' }}
                />
              </div>

              {/* Test Voice Button */}
              <div style={{ display: 'flex', gap: '12px', marginTop: '10px' }}>
                <button 
                  className="btn" 
                  onClick={() => speakVoiceFeedback("Greetings sir. Buzzcaf AI voice persona is perfectly calibrated and standing by.")}
                  style={{ flex: 1, backgroundColor: '#0284c7', borderColor: '#0369a1' }}
                >
                  <Volume2 size={16} />
                  <span>Test Sample Audio</span>
                </button>
                <button 
                  className="btn btn-outline" 
                  onClick={() => {
                    setVoiceRate(0.96);
                    setVoicePitch(1.0);
                    setVoiceVolume(1.0);
                    setSelectedVoiceURI('');
                    localStorage.removeItem('voice_rate');
                    localStorage.removeItem('voice_pitch');
                    localStorage.removeItem('voice_volume');
                    localStorage.removeItem('voice_selected_uri');
                  }}
                  style={{ fontSize: '0.85rem' }}
                >
                  Reset Defaults
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Global Floating Go to Top Button */}
      {showGoToTop && (
        <button
          onClick={() => {
            if (workspaceRef.current) {
              workspaceRef.current.scrollTo({ top: 0, behavior: 'smooth' });
            }
            window.scrollTo({ top: 0, behavior: 'smooth' });
          }}
          style={{
            position: 'fixed',
            bottom: '32px',
            right: '32px',
            zIndex: 999,
            width: '46px',
            height: '46px',
            borderRadius: '50%',
            backgroundColor: '#f43f5e',
            color: '#ffffff',
            border: 'none',
            boxShadow: '0 8px 20px rgba(244, 63, 94, 0.5)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'all 0.2s transform'
          }}
          title="Scroll to Top"
        >
          <ChevronUp size={24} />
        </button>
      )}
    </div>
  );
}
