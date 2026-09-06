import { useEffect, useState } from 'react';
import { Bookmark, Compass, MessageSquare, Send, Sparkles, Star, Trash2 } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';
import { CHANNEL_META, metaFor, workflowFor } from '../lib/channels';
import type { Topic } from '../lib/types';
import { CHAT_TOPIC_KEY } from './StudioChat';

type SubTab = 'discovered' | 'saved';

const list = (v: string[] | string | undefined) => (Array.isArray(v) ? v.join(' • ') : v || '');

export default function TopicVault() {
  const { brands, selectedChannel, setSelectedChannel, navigate, toast, confirm, refreshProjects } = useStudio();
  const [sub, setSub] = useState<SubTab>('discovered');
  const [discovered, setDiscovered] = useState<Topic[]>([]);
  const [source, setSource] = useState<string>('');
  const [discovering, setDiscovering] = useState(false);
  const [saved, setSaved] = useState<Topic[]>([]);
  const [filter, setFilter] = useState('all');

  const channels = (brands.length > 0 ? brands : CHANNEL_META.map((c) => c.id)).map((id) => ({ ...metaFor(id), id }));

  const loadSaved = async () => {
    try {
      const data = await getJson<{ topics?: Topic[] }>('/api/topics/saved');
      setSaved(data.topics || []);
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const discover = async (channel: string) => {
    setDiscovering(true);
    try {
      const data = await postJson<{ topics?: Topic[]; source?: string }>('/api/topics/discover', { channel });
      setDiscovered(data.topics || []);
      setSource(data.source || '');
    } catch (err) {
      setDiscovered([]);
      toast(describeError(err), 'error');
    } finally {
      setDiscovering(false);
    }
  };

  useEffect(() => {
    discover(selectedChannel);
    loadSaved();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pickChannel = (id: string) => {
    setSelectedChannel(id);
    discover(id);
  };

  const save = async (item: Topic) => {
    try {
      await postJson('/api/topics/save', {
        topic: item.topic,
        category: item.category || 'General',
        channel: item.channel || selectedChannel,
        viral_potential: item.viral_potential || 0,
        country: item.country || '',
        source_type: item.source_type || '',
        sources_used: item.sources_used || [],
        visual_requirements: item.visual_requirements || [],
        exclusion_audit: item.exclusion_audit || '',
        notes: item.notes || '',
      });
      toast(`Saved "${item.topic.slice(0, 40)}" to the vault.`, 'success');
      loadSaved();
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const remove = async (item: Topic) => {
    const yes = await confirm({ title: 'Delete this saved topic?', body: item.topic, confirmLabel: 'Delete', danger: true });
    if (!yes) return;
    try {
      await postJson('/api/topics/delete', { id: item.id, topic: item.topic });
      loadSaved();
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

  const develop = async (item: Topic) => {
    const brand = item.channel || selectedChannel;
    try {
      await postJson('/api/projects', { name: item.topic, brand, workflow_name: workflowFor(brand) });
      toast(`Created a ${brand} project for "${item.topic.slice(0, 40)}".`, 'success');
      await refreshProjects();
      navigate('projects');
    } catch (err) {
      toast(`Could not create the project: ${describeError(err)}`, 'error');
    }
  };

  const visibleSaved = filter === 'all' ? saved : saved.filter((t) => (t.channel || '').toLowerCase().includes(filter.toLowerCase()));

  const card = (item: Topic, kind: SubTab, idx: number) => (
    <div key={item.id || `${kind}-${idx}`} className="panel-card" style={{ padding: 24, margin: 0, display: 'flex', flexDirection: 'column', gap: 16, borderLeft: `4px solid ${kind === 'saved' ? '#f59e0b' : '#f43f5e'}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6, flexWrap: 'wrap' }}>
            {item.channel && <span className="brand-badge">{item.channel}</span>}
            {item.category && <span className="brand-badge" style={{ backgroundColor: '#1f1a29', color: '#a78bfa' }}>{item.category}</span>}
            {typeof item.viral_potential === 'number' && (
              <span style={{ fontSize: '0.8rem', color: '#4ade80', backgroundColor: '#0b261d', padding: '2px 8px', borderRadius: 4, fontWeight: 600 }}>Viral score {item.viral_potential}/10</span>
            )}
            {item.country && <span style={{ fontSize: '0.8rem', color: '#38bdf8', backgroundColor: '#0c2233', padding: '2px 8px', borderRadius: 4 }}>{item.country}</span>}
          </div>
          <h4 style={{ margin: 0, fontSize: '1.2rem', color: '#ffffff' }}>{item.topic}</h4>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {kind === 'discovered' && (
            <button type="button" className="btn btn-outline" style={{ padding: '8px 14px', fontSize: '0.85rem' }} onClick={() => save(item)}>
              <Bookmark size={15} style={{ color: '#f59e0b' }} />
              <span>Save</span>
            </button>
          )}
          <button type="button" className="btn btn-outline" style={{ padding: '8px 14px', fontSize: '0.85rem' }} onClick={() => discuss(item)}>
            <MessageSquare size={15} style={{ color: '#a78bfa' }} />
            <span>Discuss</span>
          </button>
          <button type="button" className="btn" style={{ padding: '8px 16px', fontSize: '0.85rem' }} onClick={() => develop(item)}>
            <Send size={15} />
            <span>Start project</span>
          </button>
          {kind === 'saved' && (
            <button type="button" className="btn btn-outline" style={{ padding: '8px 12px', fontSize: '0.85rem', borderColor: '#7f1d1d', color: '#fca5a5' }} onClick={() => remove(item)} aria-label="Delete">
              <Trash2 size={15} />
            </button>
          )}
        </div>
      </div>
      <div style={{ fontSize: '0.9rem', color: '#cbd5e1', display: 'flex', flexDirection: 'column', gap: 6 }}>
        {item.source_type && <div><strong>Source type:</strong> {item.source_type}</div>}
        {list(item.sources_used) && <div><strong>Sources:</strong> {list(item.sources_used)}</div>}
        {list(item.visual_requirements) && <div><strong>Visuals:</strong> {list(item.visual_requirements)}</div>}
        {item.exclusion_audit && <div style={{ fontSize: '0.85rem', color: '#4ade80', fontWeight: 600 }}>{item.exclusion_audit}</div>}
        {item.notes && <div style={{ fontStyle: 'italic', color: '#94a3b8' }}>{item.notes}</div>}
      </div>
    </div>
  );

  return (
    <div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 24 }}>
        <button type="button" className={`subtab-btn ${sub === 'discovered' ? 'active' : ''}`} onClick={() => setSub('discovered')}>
          <Compass size={18} />
          <span>Topic ideas</span>
        </button>
        <button type="button" className={`subtab-btn ${sub === 'saved' ? 'active' : ''}`} onClick={() => { setSub('saved'); loadSaved(); }}>
          <Star size={18} style={{ color: '#f59e0b' }} />
          <span>Saved vault ({saved.length})</span>
        </button>
      </div>

      {sub === 'discovered' && (
        <div>
          <div className="panel-card" style={{ marginBottom: 24 }}>
            <h3 className="panel-title"><Compass size={22} /> Topic ideas by channel</h3>
            <div style={{ display: 'flex', gap: 16, marginBottom: 20, flexWrap: 'wrap' }}>
              {channels.map((ch) => (
                <div
                  key={ch.id}
                  onClick={() => pickChannel(ch.id)}
                  style={{ flex: 1, minWidth: 200, padding: 16, borderRadius: 10, border: selectedChannel === ch.id ? '2px solid #f43f5e' : '1px solid #1e2230', backgroundColor: selectedChannel === ch.id ? '#1c1724' : '#12141d', cursor: 'pointer' }}
                >
                  <div style={{ fontSize: '1.1rem', marginBottom: 4 }}>{ch.icon} <strong style={{ color: '#ffffff' }}>{ch.id}</strong></div>
                  <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>{ch.desc}</div>
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
              <button type="button" className="btn" disabled={discovering} onClick={() => discover(selectedChannel)}>
                <Sparkles size={18} />
                <span>{discovering ? 'Loading…' : `Reload ideas for ${selectedChannel}`}</span>
              </button>
              {source && (
                <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
                  Source: {source === 'curated_seed' ? 'curated seed list (no model call)' : source}
                </span>
              )}
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            {discovered.length === 0 && !discovering && (
              <div className="panel-card" style={{ textAlign: 'center', padding: 40, color: '#94a3b8' }}>No ideas loaded for {selectedChannel}.</div>
            )}
            {discovered.map((item, idx) => card({ ...item, channel: item.channel || selectedChannel }, 'discovered', idx))}
          </div>
        </div>
      )}

      {sub === 'saved' && (
        <div>
          <div className="panel-card" style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
            <div>
              <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0 }}><Star size={22} style={{ color: '#f59e0b' }} /> Saved topics</h3>
              <p style={{ color: '#94a3b8', margin: '6px 0 0 0' }}>Bookmarked ideas across all channels.</p>
            </div>
            <select className="form-control" style={{ width: 'auto', padding: '8px 14px', fontSize: '0.85rem' }} value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="all">All channels ({saved.length})</option>
              {channels.map((ch) => <option key={ch.id} value={ch.id}>{ch.id}</option>)}
            </select>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            {visibleSaved.length === 0 ? (
              <div className="panel-card" style={{ textAlign: 'center', padding: 40, color: '#94a3b8' }}>
                <Bookmark size={36} style={{ marginBottom: 12, opacity: 0.5 }} />
                <p style={{ margin: 0 }}>Nothing saved for this filter.</p>
              </div>
            ) : (
              visibleSaved.map((item, idx) => card(item, 'saved', idx))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
