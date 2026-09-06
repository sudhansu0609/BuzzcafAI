import { useEffect, useRef, useState } from 'react';
import { Bot, Send, Trash2, X } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';
import { CHANNEL_META, strategistFor } from '../lib/channels';
import type { ChatMessage, Topic } from '../lib/types';

// The Studio Assistant: one conversation per channel with that channel's
// strategist persona. This is the landing tab (roadmap v5, 2.5) - before v5
// the chat was the third sub-tab of the Topic Vault.

export const CHAT_TOPIC_KEY = 'buzzcaf_chat_topic';

interface HistoryTurn {
  user: string;
  reply: string;
  timestamp?: string;
}

interface ChatReply {
  reply?: string;
  simulated?: boolean;
  status?: string;
  agent_name?: string;
}

const SUGGESTIONS = [
  'Give me 3 title and thumbnail hooks for this topic',
  'Outline a 10-minute video with a strong opening',
  'Which channel pillar does this fit, and why?',
  'What B-roll, maps or archive footage do we need?',
];

function stamp(value?: string): string {
  const d = value ? new Date(value) : new Date();
  return Number.isNaN(d.getTime()) ? new Date().toLocaleTimeString() : d.toLocaleTimeString();
}

function readPendingTopic(): Topic | null {
  try {
    const raw = sessionStorage.getItem(CHAT_TOPIC_KEY);
    if (!raw) return null;
    sessionStorage.removeItem(CHAT_TOPIC_KEY);
    return JSON.parse(raw) as Topic;
  } catch {
    return null;
  }
}

export default function StudioChat() {
  const { brands, selectedChannel, setSelectedChannel, toast, confirm, health } = useStudio();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [topic, setTopic] = useState<Topic | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const feedRef = useRef<HTMLDivElement | null>(null);

  const agent = strategistFor(selectedChannel);
  const channelOptions = brands.length > 0 ? brands : CHANNEL_META.map((c) => c.id);

  // A topic handed over from the vault ("Discuss this topic").
  useEffect(() => {
    const pending = readPendingTopic();
    if (pending) {
      setTopic(pending);
      if (pending.channel) setSelectedChannel(pending.channel);
    }
  }, [setSelectedChannel]);

  // Restore the persistent thread for this channel + strategist.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await getJson<{ turns?: HistoryTurn[] }>(
          `/api/topics/chat_history?channel=${encodeURIComponent(selectedChannel)}&agent_name=${encodeURIComponent(agent)}`,
        );
        if (cancelled) return;
        const restored: ChatMessage[] = [];
        for (const t of data.turns || []) {
          restored.push({ sender: 'user', text: t.user, timestamp: stamp(t.timestamp) });
          restored.push({ sender: 'agent', text: t.reply, timestamp: stamp(t.timestamp) });
        }
        setMessages(restored);
      } catch {
        if (!cancelled) setMessages([]);
      } finally {
        if (!cancelled) setLoadedFor(selectedChannel);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedChannel, agent]);

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, sending]);

  const send = async (custom?: string) => {
    const text = (custom ?? input).trim();
    if (!text || sending) return;
    const history = messages.map((m) => ({ role: m.sender === 'user' ? 'user' : 'assistant', content: m.text }));
    setMessages((prev) => [...prev, { sender: 'user', text, timestamp: stamp() }]);
    if (custom === undefined) setInput('');
    setSending(true);
    try {
      const data = await postJson<ChatReply>('/api/topics/agent_chat', {
        agent_name: agent,
        channel: selectedChannel,
        message: text,
        context_topic: topic,
        chat_history: history,
      });
      setMessages((prev) => [
        ...prev,
        {
          sender: 'agent',
          text: data.reply || '(empty reply)',
          timestamp: stamp(),
          simulated: !!data.simulated,
          error: data.status === 'error',
        },
      ]);
    } catch (err) {
      const detail = describeError(err);
      setMessages((prev) => [...prev, { sender: 'agent', text: `Could not get a reply: ${detail}`, timestamp: stamp(), error: true }]);
      toast(detail, 'error');
    } finally {
      setSending(false);
    }
  };

  const clearMemory = async () => {
    const yes = await confirm({
      title: `Clear ${agent}'s memory?`,
      body: `This deletes the stored conversation and memory for ${agent} on ${selectedChannel}. It cannot be undone.`,
      confirmLabel: 'Clear memory',
      danger: true,
    });
    if (!yes) return;
    try {
      await postJson(`/api/memory/clear?scope=agent&owner=${encodeURIComponent(agent)}`);
      await postJson(`/api/memory/clear?scope=session&owner=${encodeURIComponent(selectedChannel)}`);
      setMessages([]);
      toast('Memory cleared.', 'success');
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  return (
    <div className="panel-card" style={{ display: 'flex', flexDirection: 'column', minHeight: 'calc(100vh - 160px)', padding: 0, overflow: 'hidden' }}>
      <div style={{ backgroundColor: '#0e1017', borderBottom: '1px solid #1e2230', padding: '16px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: '50%', backgroundColor: '#1c1827', border: '1px solid #a78bfa', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#a78bfa' }}>
            <Bot size={22} />
          </div>
          <div>
            <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#ffffff' }}>{agent}</div>
            <div style={{ fontSize: '0.8rem', color: '#94a3b8', display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
              <span>Channel</span>
              <select
                className="form-control"
                style={{ padding: '2px 8px', fontSize: '0.8rem', fontWeight: 700, color: '#f43f5e', backgroundColor: '#161923', borderColor: '#334155', width: 'auto' }}
                value={selectedChannel}
                onChange={(e) => setSelectedChannel(e.target.value)}
              >
                {channelOptions.map((b) => (
                  <option key={b} value={b}>{b}</option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {topic && (
            <div style={{ backgroundColor: '#161923', border: '1px solid #232738', padding: '6px 12px', borderRadius: 8, fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>Topic: <strong style={{ color: '#ffffff' }}>{topic.topic.slice(0, 40)}{topic.topic.length > 40 ? '…' : ''}</strong></span>
              <button type="button" onClick={() => setTopic(null)} aria-label="Clear topic" style={{ background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer', display: 'flex' }}>
                <X size={14} />
              </button>
            </div>
          )}
          <button type="button" className="btn btn-outline" style={{ padding: '6px 12px', fontSize: '0.8rem', borderColor: '#7f1d1d', color: '#fca5a5' }} onClick={clearMemory}>
            <Trash2 size={14} />
            <span>Clear memory</span>
          </button>
        </div>
      </div>

      <div ref={feedRef} style={{ flex: 1, padding: 24, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 16, backgroundColor: '#08090d' }}>
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', margin: 'auto', color: '#64748b', maxWidth: 520 }}>
            <Bot size={40} style={{ opacity: 0.4, marginBottom: 12 }} />
            <p style={{ margin: 0, fontSize: '1rem', color: '#e2e8f0' }}>
              {loadedFor === selectedChannel ? `Talk to ${agent} about ${selectedChannel}.` : 'Loading the conversation…'}
            </p>
            <p style={{ fontSize: '0.85rem', marginTop: 6 }}>
              Video angles, titles, hooks, structure, research directions. Pick a topic in the Vault to bring it here.
            </p>
            {health === 'offline' && (
              <p style={{ fontSize: '0.85rem', marginTop: 12, color: '#fca5a5' }}>The Studio backend is offline; replies will fail until it is back.</p>
            )}
          </div>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={m.sender === 'user' ? 'chat-bubble-user' : 'chat-bubble-agent'}
            style={m.error ? { borderLeft: '3px solid #ef4444' } : m.simulated ? { borderLeft: '3px solid #f59e0b' } : undefined}
          >
            <div style={{ fontSize: '0.75rem', opacity: 0.6, marginBottom: 4, fontWeight: 600 }}>
              {m.sender === 'user' ? 'You' : agent} • {m.timestamp}
            </div>
            {m.simulated && !m.error && (
              <div style={{ fontSize: '0.7rem', color: '#f59e0b', marginBottom: 6, fontWeight: 600 }}>
                ⚠ SIMULATED — no AI provider responded. Configure a provider in Settings.
              </div>
            )}
            <div>{m.text}</div>
          </div>
        ))}
        {sending && (
          <div className="chat-bubble-agent" style={{ opacity: 0.7 }}>
            <em>{agent} is thinking…</em>
          </div>
        )}
      </div>

      <div style={{ backgroundColor: '#0e1017', borderTop: '1px solid #1a1d29', padding: '10px 24px', display: 'flex', gap: 10, overflowX: 'auto' }}>
        {SUGGESTIONS.map((chip) => (
          <button
            key={chip}
            type="button"
            onClick={() => send(chip)}
            disabled={sending}
            style={{ backgroundColor: '#161923', border: '1px solid #232738', color: '#e2e8f0', padding: '6px 12px', borderRadius: 9999, fontSize: '0.8rem', cursor: 'pointer', whiteSpace: 'nowrap' }}
          >
            {chip}
          </button>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        style={{ backgroundColor: '#0e1017', padding: '14px 24px', display: 'flex', gap: 12, alignItems: 'center' }}
      >
        <input
          type="text"
          className="form-control"
          placeholder={`Ask ${agent} about ${selectedChannel}…`}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          autoFocus
        />
        <button type="submit" className="btn" disabled={sending || !input.trim()} aria-label="Send">
          <Send size={18} />
        </button>
      </form>
    </div>
  );
}
