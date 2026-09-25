import { useEffect, useMemo, useRef, useState } from 'react';
import { Bot, Check, ChevronDown, ChevronRight, Copy, Send, Trash2, X, Compass, Cpu, Sparkles, FolderGit2, BarChart3, Newspaper, Search } from 'lucide-react';
import type { ToastKind } from '../lib/types';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';
import { CHANNEL_META, strategistFor } from '../lib/channels';
import Markdown from '../components/Markdown';
import type { AgentInfo, ChatMessage, Invocation, Topic } from '../lib/types';

// The Studio Assistant: one conversation per channel with that channel's
// strategist persona. This is the landing tab (roadmap v5, 2.5) - before v5
// the chat was the third sub-tab of the Topic Vault.
//
// Since v9 (A3) any registered persona can take the conversation, not just the
// five strategists: the picker is fed by /api/agents and the choice is
// remembered per channel.

export const CHAT_TOPIC_KEY = 'buzzcaf_chat_topic';
const CHAT_AGENT_KEY = 'buzzcaf_chat_agent';

interface HistoryTurn {
  user: string;
  reply: string;
  timestamp?: string;
  agent?: string;
}

interface ChatReply {
  reply?: string;
  simulated?: boolean;
  status?: string;
  agent_name?: string;
  invocations?: Invocation[];
}

// Copy text to the clipboard (with a fallback for non-secure contexts).
async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand('copy');
  } finally {
    ta.remove();
  }
}

type ToastFn = (text: string, kind?: ToastKind) => void;

function CopyButton({ text, toast, label = 'Copy' }: { text: string; toast: ToastFn; label?: string }) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    try {
      await copyToClipboard(text);
      setCopied(true);
      toast('Copied to the clipboard.', 'success');
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast('Could not copy to the clipboard.', 'error');
    }
  };
  return (
    <button
      type="button"
      onClick={onCopy}
      title="Copy text"
      style={{
        background: 'none',
        border: '1px solid var(--border-card)',
        color: copied ? '#34d399' : 'var(--text-secondary)',
        cursor: 'pointer',
        fontSize: '0.72rem',
        padding: '3px 8px',
        borderRadius: 6,
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
      }}
    >
      {copied ? <Check size={12} /> : <Copy size={12} />}
      {copied ? 'Copied' : label}
    </button>
  );
}

// Pull topic lines out of a reply — only lines that start with "Topic"
// (any case, optionally numbered/bulleted/bold), deduped.
function extractTopics(text: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const line of text.split('\n')) {
    const m = line.match(/^\s*(?:\d+[.)]\s+|[-*]\s+)?(.+)/);
    if (!m) continue;
    const item = m[1].replace(/^\*+/, '').trim();
    if (!/^topic\b/i.test(item) || seen.has(item)) continue;
    seen.add(item);
    out.push(item);
  }
  return out;
}

// Offer to save selected topics from a reply into the vault, using the exact
// /api/topics/save payload shape the Topic Vault uses.
function SendToVaultPanel({ topics, channel, toast }: { topics: string[]; channel: string; toast: ToastFn }) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const allChecked = topics.length > 0 && topics.every((t) => selected.has(t));
  const toggle = (t: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });
  const save = async () => {
    const chosen = topics.filter((t) => selected.has(t));
    if (chosen.length === 0 || saving) return;
    setSaving(true);
    let saved = 0;
    let firstError = '';
    for (const t of chosen) {
      try {
        await postJson('/api/topics/save', {
          topic: t,
          category: 'General',
          channel,
          viral_potential: 0,
          country: '',
          source_type: '',
          sources_used: [],
          visual_requirements: [],
          exclusion_audit: '',
          notes: '',
        });
        saved += 1;
      } catch (err) {
        if (!firstError) firstError = describeError(err);
      }
    }
    setSaving(false);
    if (firstError) toast(firstError, 'error');
    if (saved > 0) toast(`Saved ${saved} topic${saved === 1 ? '' : 's'} to the vault.`, 'success');
    setSelected(new Set());
  };
  return (
    <div
      style={{
        marginTop: 10,
        padding: '10px 12px',
        borderRadius: 8,
        backgroundColor: 'var(--bg-pill)',
        border: '1px solid var(--border-card)',
        fontSize: '0.82rem',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <strong style={{ color: 'var(--accent-primary)', fontSize: '0.8rem' }}>Send to Vault</strong>
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer', color: 'var(--text-secondary)' }}>
          <input type="checkbox" checked={allChecked} onChange={() => setSelected(allChecked ? new Set() : new Set(topics))} />
          All
        </label>
      </div>
      {topics.map((t) => (
        <label key={t} style={{ display: 'flex', alignItems: 'flex-start', gap: 8, cursor: 'pointer', color: 'var(--text-primary)' }}>
          <input type="checkbox" style={{ marginTop: 3 }} checked={selected.has(t)} onChange={() => toggle(t)} />
          <span style={{ userSelect: 'none' }}>{t}</span>
        </label>
      ))}
      <button
        type="button"
        className="btn"
        style={{ alignSelf: 'flex-start', padding: '5px 12px', fontSize: '0.8rem' }}
        disabled={saving || selected.size === 0}
        onClick={save}
      >
        {saving ? 'Saving…' : `Save ${selected.size > 0 ? `${selected.size} topic${selected.size === 1 ? '' : 's'}` : 'topics'}`}
      </button>
    </div>
  );
}

// One delegation the strategist made, under the reply that made it (v9, B2).
function InvocationCard({ item, toast }: { item: Invocation; toast: ToastFn }) {
  const [open, setOpen] = useState(false);
  return (
    <div style={{ backgroundColor: 'var(--bg-card)', border: '1px solid var(--border-card)', borderLeft: '3px solid var(--accent-primary)', borderRadius: 8, padding: '10px 14px', marginTop: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <strong style={{ color: 'var(--accent-primary)', fontSize: '0.82rem' }}>Delegated to {item.agent}</strong>
        {item.skipped && <span style={{ fontSize: '0.7rem', color: '#f59e0b', fontWeight: 700 }}>SKIPPED — over the per-reply limit</span>}
        {item.simulated && !item.skipped && <span style={{ fontSize: '0.7rem', color: '#f59e0b', fontWeight: 700 }}>⚠ SIMULATED</span>}
        {item.error && <span style={{ fontSize: '0.7rem', color: '#fca5a5', fontWeight: 700 }}>FAILED</span>}
      </div>
      <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: 4 }}>{item.task}</div>
      {item.output && (
        <>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.78rem', padding: '6px 0 0 0', display: 'flex', alignItems: 'center', gap: 4 }}
          >
            {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
            {open ? 'Hide what it said' : 'Show what it said'}
          </button>
          <CopyButton text={item.output} toast={toast} />
          {open && (
            <div style={{ marginTop: 8, borderTop: '1px solid var(--border-subtle)', paddingTop: 8 }}>
              <Markdown text={item.output} />
            </div>
          )}
        </>
      )}
      {item.error && <div style={{ fontSize: '0.78rem', color: '#fca5a5', marginTop: 6 }}>{item.error}</div>}
    </div>
  );
}

const SUGGESTIONS = [
  'Give me 3 title and thumbnail hooks for this topic',
  'Outline a 10-minute video with a strong opening',
  'Which channel pillar does this fit, and why?',
  'What B-roll, maps or archive footage do we need?',
];

const TOOL_ACTIONS = [
  { label: 'Check Model Status', prompt: 'Check the current local model status and loaded LLMs.' },
  { label: 'Search Trending Topics', prompt: 'Search the web for top trending video topics in our channel niche.' },
  { label: 'List Active Projects', prompt: 'List all current production projects and their stages.' },
  { label: 'Analyze Video', prompt: 'Help me analyze a competitor YouTube video URL.' },
  { label: 'Fact Check Claims', prompt: 'Please invoke FactChecker to verify factual claims in our draft.' },
  { label: 'Generate Titles', prompt: 'Please invoke TitleGenerator for 5 high-CTR YouTube titles.' },
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

function readChosenAgent(channel: string): string {
  try {
    return localStorage.getItem(`${CHAT_AGENT_KEY}:${channel}`) || '';
  } catch {
    return '';
  }
}

function writeChosenAgent(channel: string, agent: string): void {
  try {
    localStorage.setItem(`${CHAT_AGENT_KEY}:${channel}`, agent);
  } catch {
    // Storage may be unavailable; the picker still works for this session.
  }
}

export default function StudioChat() {
  const { brands, selectedChannel, setSelectedChannel, toast, confirm, health, navigate, healthInfo } = useStudio();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [topic, setTopic] = useState<Topic | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [personas, setPersonas] = useState<AgentInfo[]>([]);
  const [chosenAgent, setChosenAgent] = useState<string>(() => readChosenAgent(selectedChannel));
  const feedRef = useRef<HTMLDivElement | null>(null);

  const agent = chosenAgent || strategistFor(selectedChannel);
  const channelOptions = brands.length > 0 ? brands : CHANNEL_META.map((c) => c.id);

  // The whole roster, so the creator can hand the conversation to any persona.
  useEffect(() => {
    getJson<{ agents?: AgentInfo[] }>('/api/agents')
      .then((d) => setPersonas(d.agents || []))
      .catch(() => setPersonas([]));
  }, []);

  const personaGroups = useMemo(() => {
    const byDept = new Map<string, string[]>();
    for (const p of personas) {
      const dept = p.department || 'General';
      byDept.set(dept, [...(byDept.get(dept) || []), p.name]);
    }
    return [...byDept.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [personas]);

  const pickAgent = (name: string) => {
    setChosenAgent(name);
    writeChosenAgent(selectedChannel, name);
  };

  // Each channel remembers its own persona; switching back restores it.
  useEffect(() => {
    setChosenAgent(readChosenAgent(selectedChannel));
  }, [selectedChannel]);

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
          restored.push({ sender: 'agent', text: t.reply, timestamp: stamp(t.timestamp), agent: t.agent });
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
      const data = await postJson<ChatReply>(
        '/api/topics/agent_chat',
        {
          agent_name: agent,
          channel: selectedChannel,
          message: text,
          context_topic: topic,
          chat_history: history,
        },
        { signal: AbortSignal.timeout(300_000) },
      );
      setMessages((prev) => [
        ...prev,
        {
          sender: 'agent',
          text: data.reply || '(empty reply)',
          timestamp: stamp(),
          simulated: !!data.simulated,
          error: data.status === 'error',
          agent: data.agent_name || agent,
          invocations: data.invocations || [],
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
    <div className="panel-card chat-panel-card">
      <div className="chat-panel-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: '50%', backgroundColor: 'var(--bg-pill)', border: '1px solid var(--accent-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--accent-primary)' }}>
            <Bot size={22} />
          </div>
          <div>
            <div style={{ fontSize: '1.05rem', fontWeight: 700, color: 'var(--text-primary)' }}>{agent}</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 8, marginTop: 4, flexWrap: 'wrap' }}>
              <span>Channel</span>
              <select
                className="form-control"
                style={{ padding: '2px 8px', fontSize: '0.8rem', fontWeight: 700, color: 'var(--accent-secondary)', backgroundColor: 'var(--bg-pill)', borderColor: 'var(--border-card)', width: 'auto' }}
                value={selectedChannel}
                onChange={(e) => setSelectedChannel(e.target.value)}
              >
                {channelOptions.map((b) => (
                  <option key={b} value={b}>{b}</option>
                ))}
              </select>
              <span>Persona</span>
              <select
                className="form-control"
                style={{ padding: '2px 8px', fontSize: '0.8rem', fontWeight: 700, color: 'var(--accent-primary)', backgroundColor: 'var(--bg-pill)', borderColor: 'var(--border-card)', width: 'auto', maxWidth: 260 }}
                value={agent}
                onChange={(e) => pickAgent(e.target.value)}
                title="Any registered persona can take this conversation"
              >
                {personaGroups.length === 0 ? (
                  <option value={agent}>{agent}</option>
                ) : (
                  personaGroups.map(([dept, names]) => (
                    <optgroup key={dept} label={dept}>
                      {names.map((n) => (
                        <option key={n} value={n}>{n}</option>
                      ))}
                    </optgroup>
                  ))
                )}
              </select>
              {chosenAgent && chosenAgent !== strategistFor(selectedChannel) && (
                <button
                  type="button"
                  onClick={() => pickAgent('')}
                  style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.75rem', textDecoration: 'underline', padding: 0 }}
                >
                  back to the strategist
                </button>
              )}
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {topic && (
            <div style={{ backgroundColor: 'var(--bg-pill)', border: '1px solid var(--border-card)', padding: '6px 12px', borderRadius: 8, fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>Topic: <strong style={{ color: 'var(--text-primary)' }}>{topic.topic.slice(0, 40)}{topic.topic.length > 40 ? '…' : ''}</strong></span>
              <button type="button" onClick={() => setTopic(null)} aria-label="Clear topic" style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', display: 'flex' }}>
                <X size={14} />
              </button>
            </div>
          )}
          <button type="button" className="btn btn-outline" style={{ padding: '6px 12px', fontSize: '0.8rem', borderColor: '#ef4444', color: '#ef4444' }} onClick={clearMemory}>
            <Trash2 size={14} />
            <span>Clear memory</span>
          </button>
        </div>
      </div>

      
      {/* Studio Quick Navigation & Model Access Bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 16px',
        backgroundColor: 'rgba(255, 255, 255, 0.02)',
        borderBottom: '1px solid var(--border-card)',
        fontSize: '0.8rem',
        flexWrap: 'wrap',
        gap: 8,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          <span style={{ color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 4, marginRight: 4 }}>
            <Compass size={14} /> Studio Tabs:
          </span>
          <button type="button" className="btn btn-outline" style={{ padding: '3px 8px', fontSize: '0.75rem' }} onClick={() => navigate('topic_vault')}>
            <Newspaper size={12} style={{ marginRight: 4 }} /> Topic Vault
          </button>
          <button type="button" className="btn btn-outline" style={{ padding: '3px 8px', fontSize: '0.75rem' }} onClick={() => navigate('projects')}>
            <FolderGit2 size={12} style={{ marginRight: 4 }} /> Projects
          </button>
          <button type="button" className="btn btn-outline" style={{ padding: '3px 8px', fontSize: '0.75rem' }} onClick={() => navigate('analyze')}>
            <BarChart3 size={12} style={{ marginRight: 4 }} /> Video Intel
          </button>
          <button type="button" className="btn btn-outline" style={{ padding: '3px 8px', fontSize: '0.75rem' }} onClick={() => navigate('research')}>
            <Search size={12} style={{ marginRight: 4 }} /> Research
          </button>
          <button type="button" className="btn btn-outline" style={{ padding: '3px 8px', fontSize: '0.75rem' }} onClick={() => navigate('departments')}>
            <Sparkles size={12} style={{ marginRight: 4 }} /> 13 Depts (105 Agents)
          </button>
          <button type="button" className="btn btn-outline" style={{ padding: '3px 8px', fontSize: '0.75rem' }} onClick={() => navigate('settings')}>
            <Cpu size={12} style={{ marginRight: 4 }} /> Model Settings
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '2px 8px',
            borderRadius: 9999,
            backgroundColor: healthInfo?.model_status?.loaded ? 'rgba(34, 197, 94, 0.12)' : 'rgba(245, 158, 11, 0.12)',
            border: `1px solid ${healthInfo?.model_status?.loaded ? '#22c55e' : '#f59e0b'}`,
            color: healthInfo?.model_status?.loaded ? '#4ade80' : '#f59e0b',
            fontSize: '0.72rem',
            fontWeight: 600,
          }}>
            <Cpu size={12} />
            {healthInfo?.model_status?.active_model || 'Local Model'}
          </span>
        </div>
      </div>

      <div ref={feedRef} className="chat-panel-feed">
        {messages.length === 0 && (
          <div style={{ textAlign: 'center', margin: 'auto', color: 'var(--text-muted)', maxWidth: 520 }}>
            <Bot size={40} style={{ opacity: 0.4, marginBottom: 12 }} />
            <p style={{ margin: 0, fontSize: '1rem', color: 'var(--text-primary)' }}>
              {loadedFor === selectedChannel ? `Talk to ${agent} about ${selectedChannel}.` : 'Loading the conversation…'}
            </p>
            <p style={{ fontSize: '0.85rem', marginTop: 6, color: 'var(--text-secondary)' }}>
              Video angles, titles, hooks, structure, research directions. Pick a topic in the Vault to bring it here.
            </p>
            {health === 'offline' && (
              <p style={{ fontSize: '0.85rem', marginTop: 12, color: '#f87171' }}>The Studio backend is offline; replies will fail until it is back.</p>
            )}
          </div>
        )}
        {messages.map((m, i) => {
          const isAgent = m.sender !== 'user';
          const topics = isAgent ? extractTopics(m.text) : [];
          return (
            <div
              key={i}
              className={m.sender === 'user' ? 'chat-bubble-user' : 'chat-bubble-agent'}
              style={m.error ? { borderLeft: '3px solid #ef4444' } : m.simulated ? { borderLeft: '3px solid #f59e0b' } : undefined}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 4, fontWeight: 600 }}>
                <span style={{ fontSize: '0.75rem', opacity: 0.7 }}>
                  {m.sender === 'user' ? 'You' : m.agent || agent} • {m.timestamp}
                </span>
                {isAgent && <CopyButton text={m.text} toast={toast} />}
              </div>
              {m.simulated && !m.error && (
                <div style={{ fontSize: '0.7rem', color: '#f59e0b', marginBottom: 6, fontWeight: 600 }}>
                  ⚠ SIMULATED — no AI provider responded. Configure a provider in Settings.
                </div>
              )}
              <div>{m.text}</div>
              {topics.length >= 2 && <SendToVaultPanel topics={topics} channel={selectedChannel} toast={toast} />}
              {(m.invocations || []).map((inv, j) => <InvocationCard key={`${i}-${j}`} item={inv} toast={toast} />)}
            </div>
          );
        })}
        {sending && (
          <div className="chat-bubble-agent" style={{ opacity: 0.7 }}>
            <em>{agent} is thinking…</em>
          </div>
        )}
      </div>

      
      <div className="chat-panel-suggestions" style={{ borderBottom: '1px solid var(--border-subtle)', paddingBottom: 6 }}>
        <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 4, marginRight: 4 }}>
          <Sparkles size={12} color="var(--accent-primary)" /> Quick Tools:
        </span>
        {TOOL_ACTIONS.map((item) => (
          <button
            key={item.label}
            type="button"
            onClick={() => send(item.prompt)}
            disabled={sending}
            style={{ backgroundColor: 'var(--bg-pill)', border: '1px solid var(--accent-primary)', color: 'var(--text-primary)', padding: '4px 10px', borderRadius: 9999, fontSize: '0.75rem', cursor: 'pointer', whiteSpace: 'nowrap', opacity: sending ? 0.6 : 1 }}
          >
            {item.label}
          </button>
        ))}
      </div>

      <div className="chat-panel-suggestions">
        {SUGGESTIONS.map((chip) => (
          <button
            key={chip}
            type="button"
            onClick={() => send(chip)}
            disabled={sending}
            style={{ backgroundColor: 'var(--bg-pill)', border: '1px solid var(--border-card)', color: 'var(--text-primary)', padding: '6px 12px', borderRadius: 9999, fontSize: '0.8rem', cursor: 'pointer', whiteSpace: 'nowrap' }}
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
        className="chat-panel-form"
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
