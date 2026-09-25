import { useEffect, useState } from 'react';
import { Bookmark, Compass, MessageSquare, NotebookPen, PlusCircle, Send, Sparkles, Star, Trash2, TrendingUp } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';
import { CHANNEL_META, metaFor, workflowFor } from '../lib/channels';
import type { Topic, TopicValidation } from '../lib/types';
import { CHAT_TOPIC_KEY } from './StudioChat';

type SubTab = 'discovered' | 'saved' | 'dump';

interface DumpIdea {
  id: string;
  title: string;
  notes: string;
  channel: string;
  createdAt: string;
}

// Ideas live on disk at backend/knowledge/idea_dump.json — permanent until the
// user deletes them (or the file). localStorage is only a first-run migration
// source for ideas captured before this version existed.
function loadDump(): DumpIdea[] {
  try {
    const raw = localStorage.getItem('buzzcaf_idea_dump');
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (Array.isArray(parsed)) return parsed.filter((x): x is DumpIdea => !!x && typeof x === 'object' && typeof (x as DumpIdea).title === 'string');
  } catch {
    // Corrupt or unavailable storage: start fresh rather than break the tab.
  }
  return [];
}

function clearDumpMigration(): void {
  try {
    localStorage.removeItem('buzzcaf_idea_dump');
  } catch {
    // Ignore — migration already happened in memory.
  }
}

const list = (v: string[] | string | undefined) => (Array.isArray(v) ? v.join(' • ') : v || '');

// Small pill showing who added a topic: Dexter (the ecosystem brain) or the
// channel's Strategist agent get their own colors; anything else falls back
// to a neutral pill with the raw value.
export function sourceBadge(addedBy: string | undefined) {
  if (!addedBy) return null;
  if (addedBy === 'dexter') {
    return (
      <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#c4b5fd', backgroundColor: '#2e1b3a', padding: '2px 8px', borderRadius: 4 }}>
        Dexter
      </span>
    );
  }
  if (addedBy === 'strategist') {
    return (
      <span style={{ fontSize: '0.75rem', fontWeight: 600, color: '#38bdf8', backgroundColor: '#0c2233', padding: '2px 8px', borderRadius: 4 }}>
        Strategist
      </span>
    );
  }
  return (
    <span style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', backgroundColor: 'var(--bg-pill)', padding: '2px 8px', borderRadius: 4 }}>
      {addedBy}
    </span>
  );
}

export default function TopicVault() {
  const { brands, selectedChannel, setSelectedChannel, navigate, toast, confirm, refreshProjects } = useStudio();
  const [sub, setSub] = useState<SubTab>('discovered');
  const [discovered, setDiscovered] = useState<Topic[]>([]);
  const [source, setSource] = useState<string>('');
  const [discoverReason, setDiscoverReason] = useState<string>('');
  const [discovering, setDiscovering] = useState(false);
  const [saved, setSaved] = useState<Topic[]>([]);
  const [filter, setFilter] = useState('all');
  const [durationMin, setDurationMin] = useState(8);
  const [validations, setValidations] = useState<Record<string, TopicValidation>>({});
  const [validatingKey, setValidatingKey] = useState<string | null>(null);

  // Personal idea dump: quick capture of video ideas for later reference.
  // Persisted on disk via /api/idea-dump (backend/knowledge/idea_dump.json) —
  // permanent until the user deletes an idea or removes the file. The old
  // localStorage list is migrated once, then cleared.
  const [dump, setDump] = useState<DumpIdea[]>(() => loadDump());
  const [dumpLoaded, setDumpLoaded] = useState(false);
  const [dumpTitle, setDumpTitle] = useState('');
  const [dumpNotes, setDumpNotes] = useState('');
  const [dumpChannel, setDumpChannel] = useState(selectedChannel);
  const [dumpFilter, setDumpFilter] = useState<string>('all');

  const persistDump = async (ideas: DumpIdea[]) => {
    setDump(ideas);
    try {
      await postJson('/api/idea-dump', { ideas });
      clearDumpMigration();
    } catch (err) {
      toast(`Could not save the idea dump to disk: ${describeError(err)}`, 'error');
    }
  };

  const loadDumpFromDisk = async () => {
    try {
      const data = await getJson<{ ideas?: DumpIdea[] }>('/api/idea-dump');
      const fromDisk = Array.isArray(data.ideas) ? data.ideas : [];
      setDumpLoaded(true);
      // First run on this version: merge any localStorage-only ideas onto disk.
      if (fromDisk.length === 0 && dump.length > 0) {
        await persistDump(dump);
      } else {
        const merged = [...fromDisk];
        for (const local of dump) {
          if (!merged.some((d) => d.id === local.id)) merged.unshift(local);
        }
        setDump(merged.length === fromDisk.length ? fromDisk : merged);
        clearDumpMigration();
      }
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  useEffect(() => {
    if (!dumpLoaded) loadDumpFromDisk();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const addDumpIdeas = () => {
    // One idea per non-empty line — so you can dump a single thought or an
    // entire list of ideas in one go. Shared notes apply to every idea.
    const lines = dumpTitle.split('\n').map((l) => l.trim()).filter(Boolean);
    if (lines.length === 0) return;
    const now = new Date().toISOString();
    const fresh: DumpIdea[] = lines.map((title, i) => ({
      id: `dump-${Date.now()}-${i}-${Math.random().toString(36).slice(2, 7)}`,
      title,
      notes: dumpNotes.trim(),
      channel: dumpChannel,
      createdAt: now,
    }));
    persistDump([...fresh.reverse(), ...dump]);
    setDumpTitle('');
    setDumpNotes('');
    toast(`Dumped ${fresh.length} idea${fresh.length === 1 ? '' : 's'} to the idea dump.`, 'success');
  };

  const removeDumpIdea = async (idea: DumpIdea) => {
    const yes = await confirm({ title: 'Remove this dumped idea?', body: idea.title, confirmLabel: 'Remove', danger: true });
    if (!yes) return;
    persistDump(dump.filter((d) => d.id !== idea.id));
  };

  // Send a dumped idea into the saved vault so it flows through the normal pipeline.
  const dumpToVault = async (idea: DumpIdea) => {
    try {
      await postJson('/api/topics/save', {
        topic: idea.title,
        category: 'General',
        channel: idea.channel || selectedChannel,
        viral_potential: 0,
        country: '',
        source_type: 'idea_dump',
        sources_used: [],
        visual_requirements: [],
        exclusion_audit: '',
        notes: idea.notes,
      });
      toast(`Moved "${idea.title.slice(0, 40)}" to the saved vault.`, 'success');
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const visibleDump = dumpFilter === 'all' ? dump : dump.filter((d) => d.channel.toLowerCase() === dumpFilter.toLowerCase());

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
      const data = await postJson<{ topics?: Topic[]; source?: string; reason?: string }>('/api/topics/discover', { channel });
      setDiscovered(data.topics || []);
      setSource(data.source || '');
      setDiscoverReason(data.reason || '');
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

  const keyFor = (item: Topic) => item.id || item.topic;

  const validate = async (item: Topic): Promise<TopicValidation | null> => {
    const key = keyFor(item);
    setValidatingKey(key);
    try {
      const data = await postJson<TopicValidation>('/api/topics/validate', {
        topic: item.topic,
        channel: item.channel || selectedChannel,
      });
      setValidations((prev) => ({ ...prev, [key]: data }));
      return data;
    } catch (err) {
      toast(describeError(err), 'error');
      return null;
    } finally {
      setValidatingKey(null);
    }
  };

  const develop = async (item: Topic) => {
    const brand = item.channel || selectedChannel;
    const key = keyFor(item);
    const validation = validations[key] || (await validate(item));
    if (validation?.verdict?.recommendation === 'skip') {
      const proceed = await confirm({
        title: 'Low demand — start anyway?',
        body: validation.verdict?.demand?.reason || `The demand check recommends skipping "${item.topic}".`,
        confirmLabel: 'Start anyway',
        danger: true,
      });
      if (!proceed) return;
    }
    try {
      await postJson('/api/projects', {
        name: item.topic,
        brand,
        workflow_name: workflowFor(brand),
        target_duration_minutes: durationMin,
      });
      toast(`Created a ${brand} project for "${item.topic.slice(0, 40)}".`, 'success');
      await refreshProjects();
      navigate('projects');
    } catch (err) {
      toast(`Could not create the project: ${describeError(err)}`, 'error');
    }
  };

  const visibleSaved = filter === 'all' ? saved : saved.filter((t) => (t.channel || '').toLowerCase().includes(filter.toLowerCase()));

  const recBadge = (rec?: string) => {
    const colors = rec === 'make'
      ? { bg: '#0b261d', fg: '#4ade80' }
      : rec === 'refine'
        ? { bg: '#2e1d0f', fg: '#f59e0b' }
        : rec === 'skip'
          ? { bg: '#2a0f13', fg: '#f87171' }
          : { bg: 'var(--bg-pill)', fg: 'var(--text-secondary)' };
    return (
      <span style={{ fontSize: '0.78rem', fontWeight: 700, color: colors.fg, backgroundColor: colors.bg, padding: '3px 10px', borderRadius: 6, textTransform: 'uppercase' }}>
        {rec || 'unknown'}
      </span>
    );
  };

  const validationPanel = (item: Topic) => {
    const v = validations[keyFor(item)];
    if (!v) return null;
    const verdict = v.verdict || {};
    return (
      <div style={{ padding: 16, borderRadius: 10, backgroundColor: 'var(--bg-subcard)', border: '1px solid var(--border-card)', display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          {recBadge(verdict.recommendation)}
          {typeof verdict.demand?.score === 'number' && (
            <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Demand score: <strong style={{ color: '#e2e8f0' }}>{verdict.demand.score}</strong></span>
          )}
          {verdict.competition?.level && (
            <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
              Competition: <strong style={{ color: '#e2e8f0' }}>{verdict.competition.level}</strong>
              {verdict.competition.saturation ? ` (${verdict.competition.saturation} saturation)` : ''}
            </span>
          )}
          {v.simulated && (
            <span style={{ fontSize: '0.74rem', color: '#f59e0b', backgroundColor: '#2e1d0f', padding: '2px 8px', borderRadius: 6, fontWeight: 600 }}>
              simulated · no model running
            </span>
          )}
        </div>
        {verdict.demand?.reason && <div style={{ fontSize: '0.85rem', color: '#cbd5e1' }}>{verdict.demand.reason}</div>}
        {verdict.differentiation?.angle && (
          <div style={{ fontSize: '0.85rem', color: '#cbd5e1' }}>
            <strong>Differentiation:</strong> {verdict.differentiation.angle}
            {verdict.differentiation.gap ? ` — ${verdict.differentiation.gap}` : ''}
          </div>
        )}
        {Array.isArray(verdict.reasons) && verdict.reasons.length > 0 && (
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: '0.83rem', color: '#94a3b8' }}>
            {verdict.reasons.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        )}
        {Array.isArray(verdict.top_competitors) && verdict.top_competitors.length > 0 && (
          <div style={{ fontSize: '0.83rem', color: '#94a3b8' }}>
            <strong style={{ color: '#cbd5e1' }}>Top competitors:</strong>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
              {verdict.top_competitors.slice(0, 5).map((c, i) => (
                c.url ? (
                  <a key={i} href={c.url} target="_blank" rel="noreferrer" style={{ color: '#38bdf8' }}>
                    {c.title || c.url}{typeof c.views === 'number' ? ` — ${c.views.toLocaleString()} views` : ''}
                  </a>
                ) : (
                  <span key={i}>{c.title}{typeof c.views === 'number' ? ` — ${c.views.toLocaleString()} views` : ''}</span>
                )
              ))}
            </div>
          </div>
        )}
        {(verdict.audience_fit || verdict.competition?.note) && (
          <div style={{ fontSize: '0.83rem', color: '#94a3b8' }}>
            {verdict.audience_fit && <div><strong style={{ color: '#cbd5e1' }}>Audience fit:</strong> {verdict.audience_fit}</div>}
            {verdict.competition?.note && <div><strong style={{ color: '#cbd5e1' }}>Competition note:</strong> {verdict.competition.note}</div>}
          </div>
        )}
        {Array.isArray(verdict.risks) && verdict.risks.length > 0 && (
          <div style={{ fontSize: '0.83rem', color: '#f59e0b' }}><strong>Risks:</strong> {verdict.risks.join(' · ')}</div>
        )}
        {Array.isArray(v.steps) && v.steps.length > 0 && (
          <div style={{ borderTop: '1px solid var(--border-card)', paddingTop: 8 }}>
            <strong style={{ color: '#cbd5e1', fontSize: '0.82rem' }}>Where it searched</strong>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
              {v.steps.map((s, i) => (
                <span key={i} style={{ fontSize: '0.75rem', backgroundColor: 'var(--bg-pill)', color: 'var(--text-secondary)', padding: '2px 8px', borderRadius: 6 }}>
                  {s.source}{typeof s.count === 'number' ? ` — ${s.count}` : ''}{s.status ? ` (${s.status})` : ''}
                </span>
              ))}
            </div>
          </div>
        )}
        {Array.isArray(verdict.alternatives) && verdict.alternatives.length > 0 && (
          <div style={{ borderTop: '1px solid var(--border-card)', paddingTop: 8 }}>
            <strong style={{ color: '#cbd5e1', fontSize: '0.82rem' }}>Better topics to consider</strong>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 6 }}>
              {verdict.alternatives.map((alt, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' }}>
                  <div style={{ flex: 1, minWidth: 200 }}>
                    <div style={{ color: '#e2e8f0', fontWeight: 600, fontSize: '0.85rem' }}>{alt.topic}</div>
                    {alt.why && <div style={{ fontSize: '0.8rem', color: '#94a3b8' }}>{alt.why}</div>}
                  </div>
                  {alt.topic && (
                    <div style={{ display: 'flex', gap: 6 }}>
                      <button type="button" className="btn btn-outline" style={{ padding: '4px 10px', fontSize: '0.78rem' }} onClick={() => validate({ ...item, topic: alt.topic as string })}>Check</button>
                      <button type="button" className="btn btn-outline" style={{ padding: '4px 10px', fontSize: '0.78rem' }} onClick={() => develop({ ...item, topic: alt.topic as string })}>Start</button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  };

  const card = (item: Topic, kind: SubTab, idx: number) => (
    <div key={item.id || `${kind}-${idx}`} className="panel-card" style={{ padding: 24, margin: 0, display: 'flex', flexDirection: 'column', gap: 16, borderLeft: `4px solid ${kind === 'saved' ? '#f59e0b' : '#f43f5e'}` }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6, flexWrap: 'wrap' }}>
            {item.channel && <span className="brand-badge">{item.channel}</span>}
            {item.category && <span className="brand-badge" style={{ backgroundColor: 'var(--bg-pill)', color: 'var(--accent-primary)' }}>{item.category}</span>}
            {typeof item.viral_potential === 'number' && (
              <span style={{ fontSize: '0.8rem', color: '#4ade80', backgroundColor: '#0b261d', padding: '2px 8px', borderRadius: 4, fontWeight: 600 }}>Viral score {item.viral_potential}/10</span>
            )}
            {item.country && <span style={{ fontSize: '0.8rem', color: '#38bdf8', backgroundColor: '#0c2233', padding: '2px 8px', borderRadius: 4 }}>{item.country}</span>}
            {sourceBadge(item.added_by)}
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
          <button
            type="button"
            className="btn btn-outline"
            style={{ padding: '8px 14px', fontSize: '0.85rem' }}
            onClick={() => validate(item)}
            disabled={validatingKey === keyFor(item)}
            title="Check real demand and competition for this topic on YouTube and the web before building it"
          >
            <TrendingUp size={15} style={{ color: '#34d399' }} />
            <span>{validatingKey === keyFor(item) ? 'Checking…' : 'Check demand'}</span>
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
      {validationPanel(item)}
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
        <button type="button" className={`subtab-btn ${sub === 'dump' ? 'active' : ''}`} onClick={() => setSub('dump')}>
          <NotebookPen size={18} style={{ color: '#4ade80' }} />
          <span>Idea dump ({dump.length})</span>
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
                  style={{ flex: 1, minWidth: 200, padding: 16, borderRadius: 10, border: selectedChannel === ch.id ? '2px solid var(--border-highlight)' : '1px solid var(--border-card)', backgroundColor: selectedChannel === ch.id ? 'var(--bg-subcard)' : 'var(--bg-card)', cursor: 'pointer' }}
                >
                  <div style={{ fontSize: '1.1rem', marginBottom: 4 }}>{ch.icon} <strong style={{ color: 'var(--text-primary)' }}>{ch.id}</strong></div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{ch.desc}</div>
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 16, flexWrap: 'wrap' }}>
              <button type="button" className="btn" disabled={discovering} onClick={() => discover(selectedChannel)}>
                <Sparkles size={18} />
                <span>{discovering ? 'Loading…' : `Reload ideas for ${selectedChannel}`}</span>
              </button>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }} title="Target length for a project started from a topic (minutes). You can change it per project later on the Projects page.">
                <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>New project length (min)</span>
                <input
                  type="number"
                  min={1}
                  max={180}
                  step={1}
                  className="form-control"
                  value={durationMin}
                  onChange={(e) => setDurationMin(Math.max(1, Math.min(180, Number(e.target.value) || 1)))}
                  style={{ width: 80, padding: '6px 10px', fontSize: '0.85rem' }}
                />
              </div>
              {source === 'model' && (
                <span style={{ fontSize: '0.8rem', color: '#4ade80', backgroundColor: '#0b261d', padding: '4px 10px', borderRadius: 6, fontWeight: 600 }}>
                  Written by {metaFor(selectedChannel).strategist}
                </span>
              )}
              {source === 'model_unparsed' && (
                <span style={{ fontSize: '0.8rem', color: '#f59e0b', backgroundColor: '#2e1d0f', padding: '4px 10px', borderRadius: 6, fontWeight: 600 }}>
                  ⚠ {discoverReason || 'The model replied but its ideas could not be parsed.'}
                </span>
              )}
              {source.startsWith('curated_seed') && (
                <span style={{ fontSize: '0.8rem', color: '#f59e0b', backgroundColor: '#2e1d0f', padding: '4px 10px', borderRadius: 6, fontWeight: 600 }}>
                  ⚠ {discoverReason || 'Seed list, no model — these are the curated starter topics, not fresh ideas.'}
                  {!discoverReason && source === 'curated_seed_fallback' && ' This channel has no seed file, so these are Beyond3Baje’s.'}
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

      {sub === 'dump' && (
        <div>
          <div className="panel-card" style={{ marginBottom: 24 }}>
            <h3 className="panel-title"><NotebookPen size={22} style={{ color: '#4ade80' }} /> Idea dump</h3>
            <p style={{ color: '#94a3b8', margin: '6px 0 16px 0' }}>
              Quick-capture box for video ideas you have or stumble on. Saved permanently to <code>backend/knowledge/idea_dump.json</code> — they stay there until you delete them (or remove the file).
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, marginBottom: 16 }}>
              <textarea
                className="form-control"
                rows={5}
                placeholder={'One idea per line — dump a single thought or a whole list:\n• The last letter found in a 1940s railway station\n• Why every village has one well nobody will explain\n• The night the lighthouse went dark'}
                value={dumpTitle}
                onChange={(e) => setDumpTitle(e.target.value)}
              />
              <textarea
                className="form-control"
                rows={3}
                placeholder="Optional notes: angle, why it hits, references…"
                value={dumpNotes}
                onChange={(e) => setDumpNotes(e.target.value)}
              />
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center' }}>
                <select className="form-control" style={{ width: 'auto', padding: '8px 14px', fontSize: '0.85rem' }} value={dumpChannel} onChange={(e) => setDumpChannel(e.target.value)}>
                  {channels.map((ch) => <option key={ch.id} value={ch.id}>{ch.id}</option>)}
                </select>
                <button type="button" className="btn" style={{ padding: '8px 16px', fontSize: '0.85rem' }} onClick={addDumpIdeas} disabled={!dumpTitle.trim()}>
                  <PlusCircle size={15} />
                  <span>Dump it</span>
                </button>
              </div>
            </div>
          </div>

          <div className="panel-card" style={{ marginBottom: 24, display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 16 }}>
            <p style={{ color: '#94a3b8', margin: 0 }}>Your dumped ideas ({dump.length}).</p>
            <select className="form-control" style={{ width: 'auto', padding: '8px 14px', fontSize: '0.85rem' }} value={dumpFilter} onChange={(e) => setDumpFilter(e.target.value)}>
              <option value="all">All channels ({dump.length})</option>
              {channels.map((ch) => (
                <option key={ch.id} value={ch.id}>{ch.id}</option>
              ))}
            </select>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {visibleDump.length === 0 ? (
              <div className="panel-card" style={{ textAlign: 'center', padding: 40, color: '#94a3b8' }}>
                <NotebookPen size={36} style={{ marginBottom: 12, opacity: 0.5 }} />
                <p style={{ margin: 0 }}>Nothing dumped here yet — capture an idea above.</p>
              </div>
            ) : (
              visibleDump.map((idea) => (
                <div key={idea.id} className="panel-card" style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 12, borderLeft: '4px solid #4ade80' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 6, flexWrap: 'wrap' }}>
                        {idea.channel && <span className="brand-badge">{idea.channel}</span>}
                        <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>{new Date(idea.createdAt).toLocaleDateString()}</span>
                      </div>
                      <h4 style={{ margin: 0, fontSize: '1.2rem', color: '#ffffff' }}>{idea.title}</h4>
                    </div>
                    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                      <button type="button" className="btn btn-outline" style={{ padding: '8px 14px', fontSize: '0.85rem' }} onClick={() => dumpToVault(idea)}>
                        <Bookmark size={15} style={{ color: '#f59e0b' }} />
                        <span>To saved vault</span>
                      </button>
                      <button type="button" className="btn btn-outline" style={{ padding: '8px 12px', fontSize: '0.85rem', borderColor: '#7f1d1d', color: '#fca5a5' }} onClick={() => removeDumpIdea(idea)} aria-label="Remove">
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </div>
                  {idea.notes && (
                    <div style={{ fontSize: '0.9rem', color: '#cbd5e1' }}>
                      <strong>Notes:</strong> {idea.notes}
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
