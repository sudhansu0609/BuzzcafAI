import { useEffect, useState } from 'react';
import { Archive, X } from 'lucide-react';
import { getJson, postJson, describeError } from '../services/api';
import { useStudio } from '../state/studio';

// Clean up (2026-10-26): what the archive rules would put away now, each with
// its reason, ticked by default; the rules themselves; and "every night".
// Backend: app/services/project_archive.py, app/api/nightly_api.py.

interface Candidate { id: string; name: string; brand: string; current_step: string; days: number; reason: string }
interface Rules { enabled: boolean; stale_days: number; failed_days: number; duplicate_days: number; completed_days: number }

const RULES: { key: keyof Omit<Rules, 'enabled'>; label: string; hint: string }[] = [
  { key: 'stale_days', label: 'In progress, untouched for', hint: 'days' },
  { key: 'failed_days', label: 'A step failed and was never retried, after', hint: 'days' },
  { key: 'duplicate_days', label: 'An older copy of the same title, after', hint: 'days' },
  { key: 'completed_days', label: 'Script ready but never recorded, after', hint: 'days' },
];

export default function ArchiveCleanup({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { toast, refreshProjects } = useStudio();
  const [rules, setRules] = useState<Rules | null>(null);
  const [rows, setRows] = useState<Candidate[]>([]);
  const [picked, setPicked] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);

  const load = async () => {
    const r = await getJson<{ rules: Rules; candidates: Candidate[] }>('/api/projects/archive/candidates');
    setRules(r.rules);
    setRows(r.candidates);
    setPicked(Object.fromEntries(r.candidates.map((c) => [c.id, true])));
  };

  useEffect(() => {
    if (open) load().catch((e) => toast(`Could not load the clean-up list: ${describeError(e)}`, 'error'));
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!open) return null;

  const saveRules = async (next: Rules) => {
    setRules(next);
    try {
      await postJson('/api/projects/archive/rules', next);
      await load();
    } catch (e) {
      toast(`Could not save the rules: ${describeError(e)}`, 'error');
    }
  };

  const archive = async () => {
    const ids = rows.filter((r) => picked[r.id]).map((r) => r.id);
    if (!ids.length) return;
    setBusy(true);
    try {
      const out = await postJson<{ done: string[]; failed: { id: string }[] }>('/api/projects/archive/bulk', { ids, archived: true });
      toast(`${out.done.length} project(s) archived${out.failed.length ? `, ${out.failed.length} could not be` : ''}. Nothing was deleted.`, 'success');
      await refreshProjects();
      await load();
    } catch (e) {
      toast(`Archive failed: ${describeError(e)}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  const keep = async (id: string) => {
    try {
      await postJson(`/api/projects/${encodeURIComponent(id)}/keep`, { keep: true });
      setRows((prev) => prev.filter((r) => r.id !== id));
    } catch (e) {
      toast(`Could not pin it: ${describeError(e)}`, 'error');
    }
  };

  const muted = { color: 'var(--text-secondary)', fontSize: '0.8rem' } as const;
  const count = rows.filter((r) => picked[r.id]).length;

  return (
    <div className="modal-overlay" onClick={() => !busy && onClose()} role="dialog" aria-modal="true" aria-label="Clean up projects">
      <div className="panel-card" style={{ width: 760, maxWidth: 'calc(100vw - 32px)', maxHeight: '88vh', overflowY: 'auto', margin: 0 }}
        onClick={(e) => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <h3 style={{ margin: 0, fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: 8 }}><Archive size={18} /> Clean up projects</h3>
          <button type="button" onClick={onClose} aria-label="Close" style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer' }}><X size={18} /></button>
        </div>
        <p style={{ ...muted, margin: '6px 0 12px 0' }}>
          Archived projects keep all their files and come back with one click from the Archived tab. Anything in the production queue,
          or pinned with Keep, is never archived.
        </p>

        {rules && (
          <div style={{ display: 'grid', gap: 6, marginBottom: 14, padding: '10px 12px', border: '1px solid var(--border-card)', borderRadius: 8 }}>
            {RULES.map((r) => (
              <label key={r.key} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.84rem' }}>
                <span style={{ flex: 1 }}>{r.label}</span>
                <input type="number" min={0} max={365} className="form-control" aria-label={r.label} value={rules[r.key]}
                  onChange={(e) => setRules({ ...rules, [r.key]: Math.max(0, Number(e.target.value) || 0) })}
                  onBlur={() => saveRules(rules)} style={{ width: 70, padding: '3px 6px' }} />
                <span style={muted}>{rules[r.key] ? r.hint : 'off'}</span>
              </label>
            ))}
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.84rem' }}>
              <input type="checkbox" checked={rules.enabled} onChange={(e) => saveRules({ ...rules, enabled: e.target.checked })} />
              Apply these rules by themselves every night (03:00 run)
            </label>
          </div>
        )}

        {rows.length === 0 ? <p style={muted}>Nothing to clean up with these rules.</p> : (
          <div style={{ display: 'grid', gap: 4 }}>
            <label style={{ ...muted, display: 'flex', gap: 8, alignItems: 'center' }}>
              <input type="checkbox" checked={count === rows.length}
                onChange={(e) => setPicked(Object.fromEntries(rows.map((r) => [r.id, e.target.checked])))} />
              {rows.length} project(s) match
            </label>
            {rows.map((r) => (
              <div key={r.id} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: '0.84rem', padding: '3px 0' }}>
                <input type="checkbox" aria-label={`Archive ${r.name}`} checked={!!picked[r.id]}
                  onChange={(e) => setPicked((p) => ({ ...p, [r.id]: e.target.checked }))} />
                <span style={{ minWidth: 110, ...muted }}>{r.brand}</span>
                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.name}>{r.name}</span>
                <span style={{ ...muted, minWidth: 200 }}>{r.reason}</span>
                <button type="button" className="btn btn-outline btn-compact" title="Never archive this one by a rule" onClick={() => keep(r.id)}>Keep</button>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 14 }}>
          <button type="button" className="btn" disabled={busy || count === 0} onClick={archive}>
            {busy ? 'Archiving…' : `Archive ${count}`}
          </button>
        </div>
      </div>
    </div>
  );
}
