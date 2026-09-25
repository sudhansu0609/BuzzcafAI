import { useEffect, useState } from 'react';
import { LayoutGrid, MessageSquare, Send, TrendingUp } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';
import { CHANNEL_META, metaFor, workflowFor } from '../lib/channels';
import type { Topic } from '../lib/types';
import { CHAT_TOPIC_KEY } from './StudioChat';
import { sourceBadge } from './TopicVault';

// Kanban view of the saved topic vault, grouped by production stage. Stage
// changes (drag-drop or the per-card select) call the same
// /api/topics/update endpoint the backend exposes; there is no local-only
// state for stage — the board always reflects what is on disk.

interface Stage {
  id: string;
  label: string;
}

const STAGES: Stage[] = [
  { id: 'backlog', label: 'Backlog' },
  { id: 'potential', label: 'Potential' },
  { id: 'researching', label: 'Researching' },
  { id: 'in_progress', label: 'In Progress' },
  { id: 'published', label: 'Published' },
];

export default function Board() {
  const { brands, selectedChannel, navigate, toast } = useStudio();
  const [topics, setTopics] = useState<Topic[]>([]);
  const [channelFilter, setChannelFilter] = useState('all');
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const [quickAdd, setQuickAdd] = useState<Record<string, string>>({});

  const channels = (brands.length > 0 ? brands : CHANNEL_META.map((c) => c.id)).map((id) => ({ ...metaFor(id), id }));

  const loadTopics = async () => {
    try {
      const data = await getJson<{ topics?: Topic[] }>('/api/topics/saved');
      setTopics(data.topics || []);
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  useEffect(() => {
    loadTopics();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const keyFor = (item: Topic) => item.id || item.topic;

  const visible = channelFilter === 'all'
    ? topics
    : topics.filter((t) => (t.channel || '').toLowerCase() === channelFilter.toLowerCase());

  const updateStage = async (id: string | undefined, stage: string) => {
    if (!id) {
      toast('This topic has no id to update.', 'error');
      return;
    }
    try {
      await postJson('/api/topics/update', { id, stage });
      await loadTopics();
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const discuss = (item: Topic) => {
    try {
      sessionStorage.setItem(CHAT_TOPIC_KEY, JSON.stringify({ ...item, channel: item.channel || selectedChannel }));
    } catch {
      // Session storage unavailable; the chat still opens.
    }
    navigate('studio_chat');
  };

  const start = async (item: Topic) => {
    const brand = item.channel || selectedChannel || 'Beyond3Baje';
    try {
      await postJson('/api/projects', {
        name: item.topic,
        brand,
        workflow_name: workflowFor(brand),
        target_duration_minutes: 8,
      });
      toast(`Created a ${brand} project for "${item.topic.slice(0, 40)}".`, 'success');
      navigate('projects');
    } catch (err) {
      toast(`Could not create the project: ${describeError(err)}`, 'error');
    }
  };

  const quickAddSubmit = async (stageId: string) => {
    const text = (quickAdd[stageId] || '').trim();
    if (!text) return;
    try {
      await postJson('/api/topics/save', {
        topic: text,
        channel: channelFilter !== 'all' ? channelFilter : 'Beyond3Baje',
        category: 'General',
        stage: stageId,
        added_by: 'user',
      });
      setQuickAdd((prev) => ({ ...prev, [stageId]: '' }));
      await loadTopics();
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const onDrop = (stageId: string) => {
    if (draggingId) updateStage(draggingId, stageId);
    setDraggingId(null);
  };

  const card = (item: Topic) => {
    const id = keyFor(item);
    return (
      <div
        key={id}
        className="panel-card"
        draggable
        onDragStart={() => setDraggingId(item.id || null)}
        onDragEnd={() => setDraggingId(null)}
        style={{ padding: 16, margin: 0, display: 'flex', flexDirection: 'column', gap: 10, cursor: 'grab' }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {item.channel && <span className="brand-badge">{item.channel}</span>}
          {item.category && <span className="brand-badge" style={{ backgroundColor: 'var(--bg-pill)', color: 'var(--accent-primary)' }}>{item.category}</span>}
          {sourceBadge(item.added_by)}
        </div>
        <div style={{ fontSize: '0.95rem', color: 'var(--text-primary)', fontWeight: 600 }}>{item.topic}</div>
        {typeof item.viral_potential === 'number' && (
          <span style={{ fontSize: '0.75rem', color: '#4ade80', backgroundColor: '#0b261d', padding: '2px 8px', borderRadius: 4, fontWeight: 600, alignSelf: 'flex-start' }}>
            <TrendingUp size={12} style={{ marginRight: 4, verticalAlign: 'middle' }} />
            Viral score {item.viral_potential}/10
          </span>
        )}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
          <button type="button" className="btn btn-outline" style={{ padding: '4px 10px', fontSize: '0.75rem' }} onClick={() => discuss(item)}>
            <MessageSquare size={13} style={{ color: '#a78bfa' }} />
            <span>Discuss</span>
          </button>
          <button type="button" className="btn" style={{ padding: '4px 10px', fontSize: '0.75rem' }} onClick={() => start(item)}>
            <Send size={13} />
            <span>Start</span>
          </button>
          <select
            className="form-control"
            style={{ width: 'auto', padding: '3px 6px', fontSize: '0.72rem' }}
            value={item.stage || 'backlog'}
            onChange={(e) => updateStage(item.id, e.target.value)}
            aria-label="Move to stage"
          >
            {STAGES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </div>
      </div>
    );
  };

  return (
    <div>
      <div className="panel-card" style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
        <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0 }}>
          <LayoutGrid size={22} /> Topic board
        </h3>
        <select className="form-control" style={{ width: 'auto', padding: '8px 14px', fontSize: '0.85rem' }} value={channelFilter} onChange={(e) => setChannelFilter(e.target.value)}>
          <option value="all">All channels ({topics.length})</option>
          {channels.map((ch) => <option key={ch.id} value={ch.id}>{ch.id}</option>)}
        </select>
      </div>

      <div style={{ display: 'flex', gap: 16, overflowX: 'auto', paddingBottom: 8 }}>
        {STAGES.map((stage) => {
          const stageTopics = visible.filter((t) => (t.stage || 'backlog') === stage.id);
          return (
            <div
              key={stage.id}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => onDrop(stage.id)}
              style={{ minWidth: 280, flex: '0 0 280px', display: 'flex', flexDirection: 'column', gap: 12 }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <strong style={{ color: 'var(--text-primary)', fontSize: '0.95rem' }}>{stage.label}</strong>
                <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>{stageTopics.length}</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12, minHeight: 60 }}>
                {stageTopics.map((item) => card(item))}
              </div>
              <div style={{ display: 'flex', gap: 6 }}>
                <input
                  type="text"
                  className="form-control"
                  placeholder="Quick add…"
                  style={{ padding: '6px 10px', fontSize: '0.78rem' }}
                  value={quickAdd[stage.id] || ''}
                  onChange={(e) => setQuickAdd((prev) => ({ ...prev, [stage.id]: e.target.value }))}
                  onKeyDown={(e) => { if (e.key === 'Enter') quickAddSubmit(stage.id); }}
                />
                <button type="button" className="btn btn-outline" style={{ padding: '6px 10px', fontSize: '0.78rem' }} onClick={() => quickAddSubmit(stage.id)}>
                  Add
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
