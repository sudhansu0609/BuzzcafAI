import { useEffect, useMemo, useState } from 'react';
import { ArrowDown, ArrowUp, FolderOpen, Plus, Trash2 } from 'lucide-react';
import { useStudio } from '../state/studio';
import { postJson, describeError } from '../services/api';
import { workflowFor } from '../lib/channels';
import type { ProduceQueue } from '../lib/types';

// "Add videos" for the production queue: several videos of one channel in one
// go (POST /api/produce/queue/batch). New recordings each become a new project
// titled after the file; existing projects use the recording they were last
// produced from unless another is picked. Queued in the order shown.

interface NewRow {
  recording_path: string;
  title: string;
}

interface BatchResult {
  project_id?: string | null;
  title?: string;
  recording_path?: string | null;
  status: 'queued' | 'error';
  error?: string;
}

const titleFromPath = (path: string) => {
  const stem = (path.split(/[/\\]/).pop() || '').replace(/\.[^.]+$/, '');
  return stem.replace(/[_-]/g, ' ').replace(/\s+/g, ' ').trim() || 'Untitled video';
};

export default function AddVideosDialog({
  open,
  onClose,
  onQueued,
  activeProjectIds,
}: {
  open: boolean;
  onClose: () => void;
  onQueued: (queue: ProduceQueue) => void;
  // Projects already queued or running: they cannot be queued twice.
  activeProjectIds: Set<string>;
}) {
  const { brands, projects, selectedChannel, refreshProjects, toast } = useStudio();
  const [brand, setBrand] = useState('');
  const [tab, setTab] = useState<'new' | 'existing'>('new');
  const [rows, setRows] = useState<NewRow[]>([]);
  const [pastePath, setPastePath] = useState('');
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [existingPath, setExistingPath] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<BatchResult[]>([]);

  useEffect(() => {
    if (!open) return;
    setBrand((prev) => prev || (brands.includes(selectedChannel) ? selectedChannel : brands[0] || ''));
    setErrors([]);
  }, [open, brands, selectedChannel]);

  const channelProjects = useMemo(
    () => projects.filter((p) => p.brand === brand && !activeProjectIds.has(p.id)),
    [projects, brand, activeProjectIds],
  );

  if (!open) return null;

  const addPaths = (paths: string[]) => {
    const fresh = paths.map((p) => p.trim().replace(/^"|"$/g, '')).filter(Boolean)
      .filter((p) => !rows.some((r) => r.recording_path === p));
    setRows((prev) => [...prev, ...fresh.map((p) => ({ recording_path: p, title: titleFromPath(p) }))]);
  };

  const pickRecordings = async () => {
    setBusy(true);
    try {
      const res = await postJson<{ paths: string[] }>('/api/produce/browse_recordings', {});
      if (res.paths.length) addPaths(res.paths);
    } catch (err) {
      toast(`Could not open the file picker: ${describeError(err)}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  const pickFor = async (projectId: string) => {
    try {
      const res = await postJson<{ path: string | null }>('/api/produce/browse_recording', {});
      if (res.path) {
        setExistingPath((prev) => ({ ...prev, [projectId]: res.path as string }));
        setPicked((prev) => ({ ...prev, [projectId]: true }));
      }
    } catch (err) {
      toast(`Could not open the file picker: ${describeError(err)}`, 'error');
    }
  };

  const moveRow = (idx: number, delta: number) => setRows((prev) => {
    const next = [...prev];
    const [row] = next.splice(idx, 1);
    next.splice(Math.max(0, Math.min(next.length, idx + delta)), 0, row);
    return next;
  });

  const recordingOf = (p: (typeof projects)[number]) =>
    existingPath[p.id] ?? String((p.metadata?.recording_path as string | undefined) || '');

  const chosenExisting = channelProjects.filter((p) => picked[p.id]);
  const total = rows.length + chosenExisting.length;

  const submit = async () => {
    setBusy(true);
    setErrors([]);
    try {
      const res = await postJson<ProduceQueue & { results: BatchResult[]; queued: number }>('/api/produce/queue/batch', {
        brand,
        workflow_name: workflowFor(brand),
        items: [
          ...rows.map((r) => ({ recording_path: r.recording_path, title: r.title.trim() || undefined })),
          ...chosenExisting.map((p) => ({ project_id: p.id, recording_path: recordingOf(p) || undefined })),
        ],
      });
      onQueued(res);
      void refreshProjects();
      const failed = res.results.filter((r) => r.status === 'error');
      if (res.queued) toast(`${res.queued} ${brand} video${res.queued === 1 ? '' : 's'} added to the production queue.`, 'success');
      if (failed.length) {
        setErrors(failed);
        // Keep only what failed, so fixing it and queueing again is one click.
        const failedPaths = new Set(failed.map((f) => f.recording_path));
        const failedIds = new Set(failed.map((f) => f.project_id));
        setRows((prev) => prev.filter((r) => failedPaths.has(r.recording_path)));
        setPicked((prev) => Object.fromEntries(Object.entries(prev).filter(([id]) => failedIds.has(id))));
      } else {
        setRows([]);
        setPicked({});
        onClose();
      }
    } catch (err) {
      toast(`Could not queue the videos: ${describeError(err)}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  const tabBtn = (id: 'new' | 'existing', label: string, count: number) => (
    <button
      type="button"
      className={tab === id ? 'btn btn-sm' : 'btn btn-outline btn-sm'}
      onClick={() => setTab(id)}
      style={{ padding: '4px 12px', fontSize: '0.78rem' }}
    >
      <span>{label}{count ? ` (${count})` : ''}</span>
    </button>
  );

  const iconBtn = (Icon: typeof Plus, title: string, onClick: () => void, disabled = false) => (
    <button type="button" className="btn btn-outline btn-sm" title={title} aria-label={title} onClick={onClick} disabled={disabled || busy}
      style={{ padding: '2px 7px', fontSize: '0.72rem' }}>
      <Icon size={11} />
    </button>
  );

  return (
    <div className="modal-overlay" onClick={() => !busy && onClose()} role="dialog" aria-modal="true">
      <div
        className="panel-card"
        style={{ width: 680, maxWidth: 'calc(100vw - 32px)', maxHeight: '86vh', overflowY: 'auto', margin: 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ margin: '0 0 6px 0', color: 'var(--text-primary)', fontSize: '1.1rem' }}>Add videos to the production queue</h3>
        <p style={{ color: 'var(--text-secondary)', margin: '0 0 14px 0', fontSize: '0.82rem', lineHeight: 1.5 }}>
          Queue several videos of one channel at once. They are produced one after another, in the order below,
          with each project's saved video settings (the channel's defaults for new ones).
        </p>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 14 }}>
          <label style={{ fontSize: '0.82rem', fontWeight: 600 }}>Channel</label>
          <select className="form-control" value={brand} onChange={(e) => { setBrand(e.target.value); setPicked({}); }}
            style={{ width: 'auto', minWidth: 160 }} disabled={busy} aria-label="Channel">
            {brands.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
            {tabBtn('new', 'New recordings', rows.length)}
            {tabBtn('existing', 'Existing projects', chosenExisting.length)}
          </div>
        </div>

        {tab === 'new' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <button type="button" className="btn btn-outline btn-sm" onClick={() => void pickRecordings()} disabled={busy}
                style={{ padding: '4px 12px', fontSize: '0.78rem' }}>
                <FolderOpen size={13} />
                <span>Pick recordings…</span>
              </button>
              <input
                type="text"
                className="form-control"
                placeholder="…or paste a full path to a recording and press Add"
                value={pastePath}
                onChange={(e) => setPastePath(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { addPaths([pastePath]); setPastePath(''); } }}
                style={{ flex: 1, minWidth: 200, fontSize: '0.8rem' }}
                aria-label="Recording path"
              />
              <button type="button" className="btn btn-outline btn-sm" disabled={!pastePath.trim() || busy}
                onClick={() => { addPaths([pastePath]); setPastePath(''); }} style={{ padding: '4px 10px', fontSize: '0.78rem' }}>
                <Plus size={12} />
                <span>Add</span>
              </button>
            </div>
            {rows.length === 0 && (
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', padding: '10px 0' }}>
                No recordings yet. Each one becomes a new {brand} project, titled after the file (you can rename it here).
              </div>
            )}
            {rows.map((row, idx) => (
              <div key={row.recording_path} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border-color, rgba(255,255,255,0.1))' }}>
                <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', minWidth: 18 }}>{idx + 1}.</span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <input
                    type="text"
                    className="form-control"
                    value={row.title}
                    onChange={(e) => setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, title: e.target.value } : r)))}
                    style={{ fontSize: '0.8rem', padding: '3px 8px' }}
                    title="Project title"
                    aria-label={`Project title for recording ${idx + 1}`}
                  />
                  <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                    title={row.recording_path}>
                    {row.recording_path}
                  </div>
                </div>
                {iconBtn(ArrowUp, 'Move up', () => moveRow(idx, -1), idx === 0)}
                {iconBtn(ArrowDown, 'Move down', () => moveRow(idx, 1), idx === rows.length - 1)}
                {iconBtn(Trash2, 'Remove', () => setRows((prev) => prev.filter((_, i) => i !== idx)))}
              </div>
            ))}
          </div>
        )}

        {tab === 'existing' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {channelProjects.length === 0 && (
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', padding: '10px 0' }}>
                No {brand} projects that are not already in the queue.
              </div>
            )}
            {channelProjects.map((p) => {
              const rec = recordingOf(p);
              return (
                <div key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', borderRadius: 6, border: '1px solid var(--border-color, rgba(255,255,255,0.1))' }}>
                  <input
                    type="checkbox"
                    checked={Boolean(picked[p.id])}
                    onChange={(e) => setPicked((prev) => ({ ...prev, [p.id]: e.target.checked }))}
                    disabled={busy || !rec}
                    title={rec ? 'Queue this video' : 'Pick its recording first'}
                    aria-label={rec ? `Queue ${p.name}` : `Pick a recording for ${p.name}`}
                    style={{ width: 16, height: 16 }}
                  />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: '0.82rem', fontWeight: 500, color: 'var(--text-primary)' }}>{p.name}</div>
                    <div style={{ fontSize: '0.7rem', color: rec ? 'var(--text-muted)' : '#f59e0b', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      title={rec}>
                      {rec || 'No recording yet: pick one'}
                    </div>
                  </div>
                  <button type="button" className="btn btn-outline btn-sm" onClick={() => void pickFor(p.id)} disabled={busy}
                    style={{ padding: '2px 8px', fontSize: '0.72rem' }} title="Choose the recording for this project">
                    <FolderOpen size={11} />
                    <span>{rec ? 'Change' : 'Pick'}</span>
                  </button>
                </div>
              );
            })}
          </div>
        )}

        {errors.length > 0 && (
          <div style={{ marginTop: 12, padding: '8px 10px', borderRadius: 6, border: '1px solid rgba(239, 68, 68, 0.35)', background: 'rgba(239, 68, 68, 0.07)' }}>
            <div style={{ fontSize: '0.78rem', fontWeight: 600, color: '#f87171', marginBottom: 4 }}>Not queued:</div>
            {errors.map((e, i) => (
              <div key={i} style={{ fontSize: '0.74rem', color: 'var(--text-secondary)', overflowWrap: 'anywhere' }}>
                {e.title || e.recording_path || e.project_id}: {e.error}
              </div>
            ))}
          </div>
        )}

        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 16 }}>
          <button type="button" className="btn btn-outline" onClick={onClose} disabled={busy}>
            <span>Close</span>
          </button>
          <button type="button" className="btn" onClick={() => void submit()} disabled={busy || !brand || total === 0}>
            <span>{busy ? 'Queueing…' : `Queue ${total || ''} video${total === 1 ? '' : 's'}`.replace('  ', ' ')}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
