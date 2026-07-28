import React, { useState, useEffect } from 'react';
import { Bot, Plus, Mic, Sliders, Play, Save, RefreshCw, Cpu, Volume2, CheckCircle } from 'lucide-react';

interface Agent {
  id?: string;
  name: string;
  role: string;
  avatarColor: string;
  systemPrompt: string;
  modelProvider: string;
  modelName: string;
  temperature: number;
  voiceId: string;
  isPreset?: boolean;
}

const PRESET_SYSTEM_PROMPTS = [
  { label: '🎯 Lead Strategist', prompt: 'You are an elite YouTube Content Director. Focus on channel growth, upload cadence, target audience retention, and high-level project milestones.' },
  { label: '✍️ Script & Storyteller', prompt: 'You are a master YouTube scriptwriter. Focus on viral 3-second hooks, pacing, story arcs, retention resets, and emotional engagement.' },
  { label: '🚀 CTR & SEO Specialist', prompt: 'You are a YouTube SEO & CTR growth strategist. Optimize titles, thumbnail concepts, keyword density, tags, and audience click-through rate.' },
  { label: '🎨 Thumbnail Director', prompt: 'You are a visual Thumbnail & CTR Designer. Brainstorm high-contrast thumbnail ideas, facial emotion cues, and 2-word text overlays.' }
];

export default function AgentCreatorStudio({ onLaunchGroupChat }: { onLaunchGroupChat: (selectedIds: string[]) => void }) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [localModels, setLocalModels] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [cloningVoice, setCloningVoice] = useState(false);
  const [voiceName, setVoiceName] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  // Form State
  const [name, setName] = useState('');
  const [role, setRole] = useState('');
  const [avatarColor, setAvatarColor] = useState('#7c3aed');
  const [systemPrompt, setSystemPrompt] = useState(PRESET_SYSTEM_PROMPTS[0].prompt);
  const [modelProvider, setModelProvider] = useState('LM Studio (http://localhost:1234)');
  const [modelName, setModelName] = useState('qwen2.5-coder-7b-instruct');
  const [temperature] = useState(0.7);
  const [voiceId, setVoiceId] = useState('default-voice');
  const [editingId] = useState<string | null>(null);
  const [selectedAgentIds, setSelectedAgentIds] = useState<string[]>([]);

  useEffect(() => {
    fetchAgents();
    fetchLocalModels();
  }, []);

  const fetchAgents = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/agents-workbench/agents');
      const data = await res.json();
      setAgents(data.agents || []);
      if (data.agents && data.agents.length > 0) {
        setSelectedAgentIds(data.agents.slice(0, 3).map((a: any) => a.id));
      }
    } catch (e) {
      console.error("Failed fetching agents:", e);
    }
  };

  const fetchLocalModels = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/agents-workbench/local-models');
      const data = await res.json();
      setLocalModels(data.models || []);
    } catch (e) {
      console.error("Failed probing local LLMs:", e);
    }
  };

  const handleSaveAgent = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !role.trim()) return;

    setLoading(true);
    try {
      const payload = {
        id: editingId || undefined,
        name,
        role,
        avatarColor,
        systemPrompt,
        modelProvider,
        modelName,
        temperature,
        voiceId
      };

      const res = await fetch('http://localhost:8000/api/agents-workbench/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        fetchAgents();
        resetForm();
      }
    } catch (e) {
      console.error("Failed saving agent:", e);
    } finally {
      setLoading(false);
    }
  };

  const resetForm = () => {
    setName('');
    setRole('');
    setAvatarColor('#7c3aed');
    setSystemPrompt(PRESET_SYSTEM_PROMPTS[0].prompt);
  };

  const handleVoiceCloneSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!voiceName.trim() || !selectedFile) return;

    setCloningVoice(true);
    try {
      const formData = new FormData();
      formData.append('name', voiceName);
      formData.append('file', selectedFile);

      const res = await fetch('http://localhost:8000/api/agents-workbench/voice/clone', {
        method: 'POST',
        body: formData
      });

      if (res.ok) {
        const data = await res.json();
        setVoiceId(data.profile.id);
        alert(`✓ Voice "${voiceName}" successfully cloned! Assigned to current agent.`);
        setVoiceName('');
        setSelectedFile(null);
      }
    } catch (e) {
      console.error("Voice cloning failed:", e);
    } finally {
      setCloningVoice(false);
    }
  };

  const toggleSelectAgent = (id: string) => {
    if (selectedAgentIds.includes(id)) {
      setSelectedAgentIds(selectedAgentIds.filter(i => i !== id));
    } else {
      setSelectedAgentIds([...selectedAgentIds, id]);
    }
  };

  return (
    <div style={{ padding: '24px', color: '#f8fafc', maxWidth: '1400px', margin: '0 auto' }}>
      {/* Header Banner */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px', background: 'linear-gradient(135deg, #1e1b4b 0%, #0f172a 100%)', padding: '24px', borderRadius: '16px', border: '1px solid #312e81' }}>
        <div>
          <h1 style={{ fontSize: '1.8rem', fontWeight: 800, margin: 0, display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Bot style={{ color: '#a78bfa' }} /> Agents Creator & Personality Designer Studio
          </h1>
          <p style={{ color: '#94a3b8', margin: '6px 0 0 0', fontSize: '0.95rem' }}>
            Design custom AI agents, assign local LLMs (LM Studio / Ollama), clone voice profiles, and launch multi-agent planning rooms.
          </p>
        </div>
        <button
          onClick={() => onLaunchGroupChat(selectedAgentIds)}
          disabled={selectedAgentIds.length === 0}
          style={{
            background: selectedAgentIds.length > 0 ? 'linear-gradient(135deg, #7c3aed 0%, #f43f5e 100%)' : '#334155',
            color: '#ffffff',
            border: 'none',
            padding: '12px 24px',
            borderRadius: '10px',
            fontWeight: 700,
            cursor: selectedAgentIds.length > 0 ? 'pointer' : 'not-allowed',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontSize: '1rem',
            boxShadow: '0 4px 14px rgba(124, 58, 237, 0.4)'
          }}
        >
          <Play size={18} /> Launch Group Chat ({selectedAgentIds.length} Selected)
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.2fr', gap: '24px' }}>
        {/* Left Column: Create & Customize Agent */}
        <div style={{ background: '#0f172a', padding: '24px', borderRadius: '16px', border: '1px solid #1e293b' }}>
          <h2 style={{ fontSize: '1.2rem', fontWeight: 700, margin: '0 0 16px 0', display: 'flex', alignItems: 'center', gap: '8px', color: '#a78bfa' }}>
            <Sliders size={20} /> {editingId ? 'Edit Agent Profile' : 'Design New Custom Agent'}
          </h2>

          <form onSubmit={handleSaveAgent} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.85rem', color: '#94a3b8', marginBottom: '6px' }}>Agent Full Name</label>
              <input
                type="text"
                placeholder="e.g. Marcus Cole"
                value={name}
                onChange={e => setName(e.target.value)}
                style={{ width: '100%', padding: '10px 14px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#fff', fontSize: '0.95rem' }}
                required
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.85rem', color: '#94a3b8', marginBottom: '6px' }}>Role / Specialty Title</label>
              <input
                type="text"
                placeholder="e.g. Master Horror Scriptwriter"
                value={role}
                onChange={e => setRole(e.target.value)}
                style={{ width: '100%', padding: '10px 14px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#fff', fontSize: '0.95rem' }}
                required
              />
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.85rem', color: '#94a3b8', marginBottom: '6px' }}>Avatar Theme Color</label>
              <div style={{ display: 'flex', gap: '10px' }}>
                {['#7c3aed', '#f43f5e', '#38bdf8', '#4ade80', '#fb7185', '#f59e0b'].map(c => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setAvatarColor(c)}
                    style={{
                      width: '32px',
                      height: '32px',
                      borderRadius: '50%',
                      background: c,
                      border: avatarColor === c ? '3px solid #ffffff' : 'none',
                      cursor: 'pointer'
                    }}
                  />
                ))}
              </div>
            </div>

            <div>
              <label style={{ display: 'block', fontSize: '0.85rem', color: '#94a3b8', marginBottom: '6px' }}>Personality & System Prompt Instructions</label>
              <div style={{ display: 'flex', gap: '6px', marginBottom: '8px', flexWrap: 'wrap' }}>
                {PRESET_SYSTEM_PROMPTS.map(p => (
                  <button
                    key={p.label}
                    type="button"
                    onClick={() => setSystemPrompt(p.prompt)}
                    style={{ background: '#1e293b', border: '1px solid #334155', color: '#cbd5e1', padding: '4px 8px', borderRadius: '6px', fontSize: '0.75rem', cursor: 'pointer' }}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <textarea
                rows={4}
                value={systemPrompt}
                onChange={e => setSystemPrompt(e.target.value)}
                placeholder="Define instructions, tone of voice, domain expertise, and behavioral boundaries..."
                style={{ width: '100%', padding: '10px 14px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#fff', fontSize: '0.9rem', resize: 'vertical' }}
              />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', color: '#94a3b8', marginBottom: '6px' }}>Local LLM Provider</label>
                <select
                  value={modelProvider}
                  onChange={e => setModelProvider(e.target.value)}
                  style={{ width: '100%', padding: '10px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#fff', fontSize: '0.85rem' }}
                >
                  <option value="LM Studio (http://localhost:1234)">LM Studio (Port 1234)</option>
                  <option value="Ollama (http://localhost:11434)">Ollama / Open-WebUI (Port 11434)</option>
                </select>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', color: '#94a3b8', marginBottom: '6px' }}>Assigned Local Model</label>
                <select
                  value={modelName}
                  onChange={e => setModelName(e.target.value)}
                  style={{ width: '100%', padding: '10px', background: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#fff', fontSize: '0.85rem' }}
                >
                  {localModels.map(m => (
                    <option key={m.id} value={m.id}>{m.name}</option>
                  ))}
                  {localModels.length === 0 && (
                    <option value="qwen2.5-coder-7b-instruct">qwen2.5-coder-7b-instruct</option>
                  )}
                </select>
              </div>
            </div>

            <button
              type="submit"
              disabled={loading}
              style={{
                background: 'linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%)',
                color: '#fff',
                border: 'none',
                padding: '12px',
                borderRadius: '8px',
                fontWeight: 700,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '8px',
                marginTop: '8px'
              }}
            >
              <Save size={18} /> {editingId ? 'Update Agent Profile' : 'Save Agent to Studio'}
            </button>
          </form>

          {/* Voice Cloning Sub-Section */}
          <div style={{ marginTop: '24px', paddingTop: '20px', borderTop: '1px solid #1e293b' }}>
            <h3 style={{ fontSize: '1rem', fontWeight: 700, margin: '0 0 10px 0', color: '#38bdf8', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <Mic size={18} /> Zero-Shot Voice Cloning Studio (F5-TTS)
            </h3>
            <form onSubmit={handleVoiceCloneSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <input
                type="text"
                placeholder="Voice Profile Name (e.g. Host Accent)"
                value={voiceName}
                onChange={e => setVoiceName(e.target.value)}
                style={{ padding: '8px 12px', background: '#1e293b', border: '1px solid #334155', borderRadius: '6px', color: '#fff', fontSize: '0.85rem' }}
              />
              <input
                type="file"
                accept="audio/*"
                onChange={e => setSelectedFile(e.target.files ? e.target.files[0] : null)}
                style={{ fontSize: '0.8rem', color: '#94a3b8' }}
              />
              <button
                type="submit"
                disabled={cloningVoice || !selectedFile}
                style={{
                  background: selectedFile ? '#0284c7' : '#334155',
                  color: '#fff',
                  border: 'none',
                  padding: '8px 14px',
                  borderRadius: '6px',
                  fontWeight: 600,
                  fontSize: '0.85rem',
                  cursor: selectedFile ? 'pointer' : 'not-allowed'
                }}
              >
                {cloningVoice ? 'Cloning Voice Vector...' : '🎙️ Extract & Clone Voice Profile'}
              </button>
            </form>
          </div>
        </div>

        {/* Right Column: Agents Library Grid */}
        <div>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
            <h2 style={{ fontSize: '1.2rem', fontWeight: 700, margin: 0, color: '#f8fafc' }}>
              Active Agents Library ({agents.length})
            </h2>
            <button onClick={fetchAgents} style={{ background: '#1e293b', color: '#94a3b8', border: '1px solid #334155', padding: '6px 12px', borderRadius: '6px', fontSize: '0.8rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <RefreshCw size={14} /> Sync Registry
            </button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '14px' }}>
            {agents.map(a => {
              const isSelected = selectedAgentIds.includes(a.id || '');
              return (
                <div
                  key={a.id}
                  style={{
                    background: '#0f172a',
                    borderRadius: '12px',
                    border: `1.5px solid ${isSelected ? '#7c3aed' : '#1e293b'}`,
                    padding: '16px',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '10px'
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                      <div style={{ width: '44px', height: '44px', borderRadius: '50%', background: a.avatarColor, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 800, fontSize: '1.2rem' }}>
                        {a.name.charAt(0)}
                      </div>
                      <div>
                        <h3 style={{ margin: 0, fontSize: '1.05rem', fontWeight: 700, color: '#f8fafc' }}>{a.name}</h3>
                        <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>{a.role}</span>
                      </div>
                    </div>

                    <button
                      onClick={() => toggleSelectAgent(a.id || '')}
                      style={{
                        background: isSelected ? '#7c3aed22' : '#1e293b',
                        color: isSelected ? '#a78bfa' : '#94a3b8',
                        border: `1px solid ${isSelected ? '#7c3aed' : '#334155'}`,
                        padding: '6px 12px',
                        borderRadius: '6px',
                        fontSize: '0.8rem',
                        fontWeight: 600,
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px'
                      }}
                    >
                      {isSelected ? <CheckCircle size={14} /> : <Plus size={14} />} {isSelected ? 'In Chatroom' : 'Add to Chat'}
                    </button>
                  </div>

                  <p style={{ fontSize: '0.85rem', color: '#cbd5e1', background: '#1e293b44', padding: '10px', borderRadius: '6px', margin: 0, fontStyle: 'italic' }}>
                    "{a.systemPrompt.slice(0, 140)}..."
                  </p>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.78rem', color: '#94a3b8', paddingTop: '6px' }}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <Cpu size={14} style={{ color: '#38bdf8' }} /> {a.modelName}
                    </span>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <Volume2 size={14} style={{ color: '#4ade80' }} /> Cloned Voice Active
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
