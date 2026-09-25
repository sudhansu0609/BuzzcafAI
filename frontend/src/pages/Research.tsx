import { useState } from 'react';
import { Archive, BookOpen, Newspaper, NotebookPen, Search, Send } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';
import { workflowFor } from '../lib/channels';
import type { DeepResearchResult, SourceItem } from '../lib/types';

type ResearchKind = 'news' | 'archives' | 'books';

interface DumpIdea {
  id: string;
  title: string;
  notes: string;
  channel: string;
  createdAt: string;
}

const KIND_META: Record<ResearchKind, { label: string; icon: React.ReactNode }> = {
  books: { label: 'Books', icon: <BookOpen size={15} /> },
  archives: { label: 'Archives', icon: <Archive size={15} /> },
  news: { label: 'News', icon: <Newspaper size={15} /> },
};

// Public archives, books and newspaper search (Feature A) — a research aid
// alongside the topic vault, not tied to a specific channel. Ideas found here
// flow into the same idea dump and project pipeline as everywhere else.
export default function Research() {
  const { selectedChannel, toast, refreshProjects, navigate } = useStudio();
  const [query, setQuery] = useState('');
  const [kinds, setKinds] = useState<Set<ResearchKind>>(new Set(['news', 'archives', 'books']));
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DeepResearchResult | null>(null);

  const toggleKind = (k: ResearchKind) => {
    setKinds((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
  };

  const search = async () => {
    if (!query.trim() || kinds.size === 0) return;
    setLoading(true);
    try {
      const data = await getJson<DeepResearchResult>(
        `/api/research/sources?q=${encodeURIComponent(query.trim())}&kinds=${[...kinds].join(',')}`,
      );
      setResult(data);
    } catch (err) {
      toast(describeError(err), 'error');
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

  const toIdeaDump = async (item: SourceItem) => {
    try {
      const current = await getJson<{ ideas?: DumpIdea[] }>('/api/idea-dump');
      const existing = Array.isArray(current.ideas) ? current.ideas : [];
      const idea: DumpIdea = {
        id: `dump-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        title: item.title,
        notes: `${item.source} — ${item.url}`,
        channel: selectedChannel,
        createdAt: new Date().toISOString(),
      };
      await postJson('/api/idea-dump', { ideas: [idea, ...existing] });
      toast(`Added "${item.title.slice(0, 40)}" to the idea dump.`, 'success');
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const startProject = async (item: SourceItem) => {
    try {
      await postJson('/api/projects', {
        name: item.title,
        brand: selectedChannel,
        workflow_name: workflowFor(selectedChannel),
      });
      toast(`Created a ${selectedChannel} project for "${item.title.slice(0, 40)}".`, 'success');
      await refreshProjects();
      navigate('projects');
    } catch (err) {
      toast(`Could not create the project: ${describeError(err)}`, 'error');
    }
  };

  const groups: Array<{ key: ResearchKind; items: SourceItem[] }> = result
    ? [
        { key: 'books', items: result.by_kind?.books ?? result.results.filter((r) => r.kind === 'book') },
        { key: 'archives', items: result.by_kind?.archives ?? result.results.filter((r) => r.kind === 'archive') },
        { key: 'news', items: result.by_kind?.news ?? result.results.filter((r) => r.kind === 'news') },
      ]
    : [];

  const resultCard = (item: SourceItem, idx: number) => (
    <div key={`${item.url}-${idx}`} className="panel-card" style={{ padding: 20, margin: 0, display: 'flex', flexDirection: 'column', gap: 10, borderLeft: '4px solid #38bdf8' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span className="brand-badge">{item.source}</span>
      </div>
      <a href={item.url} target="_blank" rel="noreferrer" style={{ color: '#e2e8f0', fontSize: '1.05rem', fontWeight: 600, textDecoration: 'none' }}>
        {item.title}
      </a>
      {item.snippet && <div style={{ fontSize: '0.88rem', color: '#94a3b8' }}>{item.snippet}</div>}
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginTop: 4 }}>
        <button type="button" className="btn btn-outline" style={{ padding: '6px 12px', fontSize: '0.82rem' }} onClick={() => toIdeaDump(item)}>
          <NotebookPen size={14} style={{ color: '#4ade80' }} />
          <span>To idea dump</span>
        </button>
        <button type="button" className="btn" style={{ padding: '6px 14px', fontSize: '0.82rem' }} onClick={() => startProject(item)}>
          <Send size={14} />
          <span>Start project</span>
        </button>
      </div>
    </div>
  );

  return (
    <div>
      <div className="panel-card" style={{ marginBottom: 24 }}>
        <h3 className="panel-title"><Newspaper size={22} /> Research</h3>
        <p style={{ color: '#94a3b8', margin: '6px 0 16px 0' }}>
          Search public archives, books and newspapers for source material. Results are not filtered by channel —
          sending a result to the idea dump or starting a project uses the current channel (<strong style={{ color: 'var(--text-primary)' }}>{selectedChannel}</strong>).
        </p>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', marginBottom: 14 }}>
          <input
            type="text"
            className="form-control"
            style={{ flex: 1, minWidth: 240 }}
            placeholder="Search a topic, person, or event…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && search()}
          />
          <button type="button" className="btn" disabled={loading || !query.trim() || kinds.size === 0} onClick={search}>
            <Search size={16} />
            <span>{loading ? 'Searching…' : 'Search'}</span>
          </button>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {(Object.keys(KIND_META) as ResearchKind[]).map((k) => (
            <button
              key={k}
              type="button"
              className={`subtab-btn ${kinds.has(k) ? 'active' : ''}`}
              onClick={() => toggleKind(k)}
            >
              {KIND_META[k].icon}
              <span>{KIND_META[k].label}</span>
            </button>
          ))}
        </div>
        {kinds.size === 0 && (
          <p style={{ color: '#f87171', fontSize: '0.83rem', marginTop: 10 }}>Turn on at least one source type to search.</p>
        )}
      </div>

      {result && Array.isArray(result.sources_searched) && result.sources_searched.length > 0 && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 20 }}>
          {result.sources_searched.map((s, i) => (
            <span key={`${s.source}-${i}`} style={{ fontSize: '0.78rem', color: '#94a3b8', backgroundColor: 'var(--bg-pill)', padding: '3px 10px', borderRadius: 6 }}>
              {s.source} — {s.count}
            </span>
          ))}
        </div>
      )}

      {result && result.results.length === 0 && (
        <div className="panel-card" style={{ textAlign: 'center', padding: 40, color: '#94a3b8' }}>
          No results for "{result.query}". Try a different query or turn on more source types.
        </div>
      )}

      {result && result.results.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 28 }}>
          {groups.filter((g) => g.items.length > 0).map((g) => (
            <div key={g.key}>
              <h4 style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-primary)', margin: '0 0 12px 0' }}>
                {KIND_META[g.key].icon}
                <span>{KIND_META[g.key].label}</span>
              </h4>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                {g.items.map((item, idx) => resultCard(item, idx))}
              </div>
            </div>
          ))}
        </div>
      )}

      {!result && !loading && (
        <div className="panel-card" style={{ textAlign: 'center', padding: 40, color: '#94a3b8' }}>
          Search above to pull source material from books, archives and newspapers.
        </div>
      )}
    </div>
  );
}
