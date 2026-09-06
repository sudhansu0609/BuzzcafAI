import { apiFetch } from '../../services/http';
import React, { useState, useEffect, useRef } from 'react';
import { Send, Users, ArrowLeft, Sparkles } from 'lucide-react';

interface ChatMessage {
  id: string;
  sender: string;
  role?: string;
  avatarColor?: string;
  text: string;
  timestamp: string;
  /** True when the model server was unreachable and the text is canned. */
  simulated?: boolean;
  isUser?: boolean;
}

export default function AgentsGroupChat({
  selectedAgentIds,
  onBackToStudio
}: {
  selectedAgentIds: string[];
  onBackToStudio: () => void;
}) {
  const [agents, setAgents] = useState<any[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);

  const chatEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchActiveAgents();
  }, [selectedAgentIds]);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const fetchActiveAgents = async () => {
    try {
      const res = await apiFetch('/api/agents-workbench/agents');
      const data = await res.json();
      const active = (data.agents || []).filter((a: any) => selectedAgentIds.includes(a.id));
      setAgents(active);

      // System greeting message
      setMessages([
        {
          id: 'welcome-01',
          sender: 'Buzzcaf Group Chat Room',
          text: `Welcome! Active agents: ${active.map((a: any) => a.name).join(', ')}. Ask a question to start multi-agent planning.`,
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          avatarColor: '#7c3aed'
        }
      ]);
    } catch (e) {
      console.error("Failed fetching active chat agents:", e);
    }
  };

  const handleSendMessage = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!inputMessage.trim() || isGenerating) return;

    const userText = inputMessage;
    setInputMessage('');

    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      sender: 'You',
      text: userText,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      isUser: true,
      avatarColor: '#38bdf8'
    };

    setMessages(prev => [...prev, userMsg]);
    setIsGenerating(true);

    try {
      const payload = {
        agentIds: selectedAgentIds,
        userMessage: userText,
        conversationHistory: messages.map(m => ({ sender: m.isUser ? 'user' : 'assistant', text: m.text }))
      };

      const res = await apiFetch('/api/agents-workbench/chat/group-chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        let detail = `${res.status} ${res.statusText}`;
        try {
          const body = await res.json();
          if (body && typeof body.detail === 'string') detail = body.detail;
        } catch {
          // no JSON body
        }
        throw new Error(detail);
      }
      {
        const data = await res.json();
        const agentResponses = data.agentResponses || [];

        agentResponses.forEach((resp: any, idx: number) => {
          setTimeout(() => {
            const agentMsg: ChatMessage = {
              id: `resp-${Date.now()}-${idx}`,
              sender: resp.agentName,
              role: resp.agentRole,
              avatarColor: resp.avatarColor || '#7c3aed',
              text: resp.response,
              timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
              simulated: !!resp.simulated
            };
            setMessages(prev => [...prev, agentMsg]);
          }, idx * 600);
        });
      }
    } catch (e) {
      // A failed room used to leave the user's message hanging with no reply.
      console.error("Failed sending group chat message:", e);
      setMessages(prev => [...prev, {
        id: `err-${Date.now()}`,
        sender: 'Buzzcaf Group Chat Room',
        text: `Could not get replies: ${e instanceof Error ? e.message : String(e)}`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        avatarColor: '#7f1d1d',
        simulated: true
      }]);
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div style={{ padding: '24px', color: '#f8fafc', maxWidth: '1200px', margin: '0 auto', height: 'calc(100vh - 80px)', display: 'flex', flexDirection: 'column' }}>
      {/* Header Bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#0f172a', padding: '16px 24px', borderRadius: '14px', border: '1px solid #1e293b', marginBottom: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <button
            onClick={onBackToStudio}
            style={{ background: '#1e293b', color: '#cbd5e1', border: '1px solid #334155', padding: '8px 12px', borderRadius: '8px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.85rem' }}
          >
            <ArrowLeft size={16} /> Studio Workbench
          </button>
          <div>
            <h1 style={{ fontSize: '1.2rem', fontWeight: 800, margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Users style={{ color: '#a78bfa' }} /> Agents Group Chat Room
            </h1>
            <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
              Active Agents: {agents.map(a => a.name).join(', ')}
            </span>
          </div>
        </div>

      </div>

      {/* Main Conversation Feed */}
      <div style={{ flex: 1, background: '#090d16', borderRadius: '14px', border: '1px solid #1e293b', padding: '20px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {messages.map(m => (
          <div
            key={m.id}
            style={{
              display: 'flex',
              gap: '12px',
              alignSelf: m.isUser ? 'flex-end' : 'flex-start',
              maxWidth: '80%'
            }}
          >
            {!m.isUser && (
              <div style={{ width: '38px', height: '38px', borderRadius: '50%', background: m.avatarColor || '#7c3aed', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 800, fontSize: '1rem', flexShrink: 0 }}>
                {m.sender.charAt(0)}
              </div>
            )}

            <div style={{ background: m.isUser ? '#1e1b4b' : '#0f172a', padding: '14px 18px', borderRadius: '12px', border: `1px solid ${m.simulated ? '#f59e0b' : m.isUser ? '#4338ca' : '#1e293b'}` }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px', gap: '12px' }}>
                <span style={{ fontWeight: 700, fontSize: '0.9rem', color: m.isUser ? '#a78bfa' : '#38bdf8' }}>{m.sender}</span>
                {m.role && <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>• {m.role}</span>}
                <span style={{ fontSize: '0.7rem', color: '#64748b' }}>{m.timestamp}</span>
              </div>

              {m.simulated && (
                <div style={{ fontSize: '0.7rem', color: '#f59e0b', fontWeight: 700, marginBottom: '6px', letterSpacing: '0.03em' }}>
                  ⚠ SIMULATED — model server unreachable
                </div>
              )}

              <p style={{ margin: 0, fontSize: '0.92rem', color: '#f8fafc', lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
                {m.text}
              </p>

            </div>

            {m.isUser && (
              <div style={{ width: '38px', height: '38px', borderRadius: '50%', background: '#38bdf8', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 800, fontSize: '1rem', flexShrink: 0 }}>
                U
              </div>
            )}
          </div>
        ))}
        {isGenerating && (
          <div style={{ color: '#a78bfa', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 12px' }}>
            <Sparkles className="animate-spin" size={16} /> Agents are collaborating & thinking...
          </div>
        )}
        <div ref={chatEndRef} />
      </div>

      {/* Input Form */}
      <form onSubmit={handleSendMessage} style={{ display: 'flex', gap: '10px', marginTop: '16px' }}>
        <input
          type="text"
          placeholder="Ask the group agents a question or give them a task..."
          value={inputMessage}
          onChange={e => setInputMessage(e.target.value)}
          style={{ flex: 1, padding: '14px 18px', background: '#0f172a', border: '1px solid #1e293b', borderRadius: '10px', color: '#fff', fontSize: '0.95rem' }}
        />
        <button
          type="submit"
          disabled={isGenerating || !inputMessage.trim()}
          style={{
            background: 'linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%)',
            color: '#fff',
            border: 'none',
            padding: '14px 24px',
            borderRadius: '10px',
            fontWeight: 700,
            cursor: isGenerating || !inputMessage.trim() ? 'not-allowed' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}
        >
          <Send size={18} /> Send to Agents
        </button>
      </form>
    </div>
  );
}
