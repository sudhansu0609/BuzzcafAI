import { useCallback, useEffect, useRef, useState } from 'react';
import { PenLine } from 'lucide-react';
import { describeError, getJson, postJson } from '../services/api';
import YouTubeChannels, { type YtStatus } from '../components/YouTubeChannels';

// Bulk Editor: edit titles and descriptions across a whole YouTube channel
// (backend integrations/youtube_bulk_edit.py, app/api/bulk_edit_api.py).
// Preview is a dry run; Apply backs up the originals first and wants the count
// typed back; Restore puts any backup back. The channels connected at the top
// are the same ones the Projects page publishes to.

type FieldForm = { remove: string; replace: string; prepend: string; append: string };
type Form = { title: FieldForm; description: FieldForm; separator: string; privacy: string[] };
type Item = {
  id: string; privacy: string; published_at: string;
  title: string; new_title: string; description: string; new_description: string; problems: string[];
};
type Preview = { preview_id: string; channel_id: string; total_videos: number; items: Item[]; max_per_run: number };
type Job = {
  state: 'idle' | 'running' | 'done'; kind?: string; total?: number; done?: number; failed?: number;
  backup?: string; log?: string[]; message?: string;
};
type Backup = { name: string; created_at: string; label: string; count: number };

const EMPTY_FIELD: FieldForm = { remove: '', replace: '', prepend: '', append: '' };
const EMPTY: Form = { title: { ...EMPTY_FIELD }, description: { ...EMPTY_FIELD }, separator: '\n\n', privacy: ['public', 'unlisted', 'private'] };
const FORM_KEY = 'buzzcaf.bulkEdit.form';

function loadForm(): Form {
  try {
    const raw = localStorage.getItem(FORM_KEY);
    return raw ? { ...EMPTY, ...JSON.parse(raw) } : EMPTY;
  } catch {
    return EMPTY;
  }
}

const lines = (text: string) => text.split('\n').map((l) => l.trim()).filter(Boolean);

function toRule(f: FieldForm, separator?: string) {
  return {
    remove: lines(f.remove),
    replace: lines(f.replace).map((l) => {
      const [find, ...rest] = l.split('=>');
      return [find.trim(), rest.join('=>').trim()];
    }).filter(([find]) => find),
    prepend: f.prepend,
    append: f.append,
    ...(separator !== undefined ? { separator } : {}),
  };
}

export default function BulkEdit() {
  const [yt, setYt] = useState<YtStatus | null>(null);
  const [channel, setChannel] = useState('');
  const [form, setForm] = useState<Form>(loadForm);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [job, setJob] = useState<Job | null>(null);
  const [backups, setBackups] = useState<Backup[]>([]);
  const [backup, setBackup] = useState('');
  const [confirm, setConfirm] = useState<{ kind: 'apply' | 'restore'; count: number; note: string } | null>(null);
  const [typed, setTyped] = useState('');
  const poll = useRef<number | null>(null);

  useEffect(() => {
    try { localStorage.setItem(FORM_KEY, JSON.stringify(form)); } catch { /* per-viewer convenience only */ }
  }, [form]);

  const signedIn = (yt?.channels || []).filter((c) => c.signed_in);

  const loadBackups = useCallback(async (cid: string) => {
    if (!cid) { setBackups([]); return; }
    try {
      const r = await getJson<{ backups: Backup[] }>(`/api/bulk-edit/backups?channel_id=${encodeURIComponent(cid)}`);
      setBackups(r.backups);
      setBackup(r.backups[0]?.name || '');
    } catch {
      setBackups([]);
    }
  }, []);

  const watchJob = useCallback(() => {
    if (poll.current) window.clearInterval(poll.current);
    const tick = async () => {
      const j = await getJson<Job>('/api/bulk-edit/job').catch(() => null);
      if (!j) return;
      setJob(j);
      if (j.state !== 'running' && poll.current) {
        window.clearInterval(poll.current);
        poll.current = null;
      }
    };
    poll.current = window.setInterval(tick, 1500);
    void tick();
  }, []);

  useEffect(() => {
    getJson<Job>('/api/bulk-edit/job').then((j) => { if (j.state === 'running') watchJob(); else if (j.state === 'done') setJob(j); }).catch(() => undefined);
    return () => { if (poll.current) window.clearInterval(poll.current); };
  }, [watchJob]);

  useEffect(() => {
    if (!channel && signedIn.length) setChannel(signedIn[0].id);
  }, [signedIn, channel]);

  useEffect(() => { setPreview(null); void loadBackups(channel); }, [channel, loadBackups]);

  const setField = (side: 'title' | 'description', key: keyof FieldForm, value: string) =>
    setForm((f) => ({ ...f, [side]: { ...f[side], [key]: value } }));

  const runPreview = async () => {
    setBusy('preview');
    setError('');
    setPreview(null);
    try {
      const p = await postJson<Preview>('/api/bulk-edit/preview', {
        channel_id: channel,
        rules: { title: toRule(form.title), description: toRule(form.description, form.separator), privacy: form.privacy },
      }, { signal: AbortSignal.timeout(600_000) });
      setPreview(p);
      setSelected(new Set(p.items.filter((i) => !i.problems.length).slice(0, p.max_per_run).map((i) => i.id)));
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy('');
    }
  };

  const askRestore = async () => {
    setBusy('restore');
    setError('');
    try {
      const r = await postJson<{ count: number }>('/api/bulk-edit/restore/check', { channel_id: channel, backup });
      if (!r.count) setError('Every video already matches that backup; nothing to restore.');
      else setConfirm({ kind: 'restore', count: r.count, note: `Put back the titles and descriptions of ${r.count} video(s) from ${backup}.` });
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy('');
    }
  };

  const confirmed = async () => {
    if (!confirm) return;
    setError('');
    try {
      if (confirm.kind === 'apply' && preview) {
        await postJson('/api/bulk-edit/apply', { preview_id: preview.preview_id, ids: [...selected], confirm: Number(typed) });
        setPreview(null);
      } else {
        await postJson('/api/bulk-edit/restore', { channel_id: channel, backup, confirm: Number(typed) });
      }
      setConfirm(null);
      setTyped('');
      watchJob();
      void loadBackups(channel);
    } catch (err) {
      setError(describeError(err));
    }
  };

  const running = job?.state === 'running';
  const channelTitle = signedIn.find((c) => c.id === channel)?.title || '';
  const muted = { fontSize: '0.8rem', color: 'var(--text-secondary)' } as const;

  const full = { width: '100%', boxSizing: 'border-box' } as const;
  const area = { ...full, minHeight: 72, resize: 'vertical', fontSize: '0.85rem', padding: '10px 12px' } as const;
  const input = { ...full, fontSize: '0.85rem', padding: '9px 12px' } as const;
  const hint = { fontWeight: 400, fontSize: '0.75rem', color: 'var(--text-muted)' } as const;

  const fieldColumn = (side: 'title' | 'description') => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, minWidth: 0 }}>
      <b style={{ textTransform: 'capitalize' }}>{side}</b>
      <div className="form-group" style={{ minWidth: 0, flex: '0 0 auto' }}>
        <label>Remove <span style={hint}>(one per line; /regex/i also works)</span></label>
        <textarea className="form-control" style={area} value={form[side].remove} aria-label={`Remove (${side})`}
          placeholder={side === 'title' ? 'clickbait\nSHOCKING' : ''} onChange={(e) => setField(side, 'remove', e.target.value)} />
      </div>
      <div className="form-group" style={{ minWidth: 0, flex: '0 0 auto' }}>
        <label>Replace <span style={hint}>(find =&gt; replacement, one per line)</span></label>
        <textarea className="form-control" style={area} value={form[side].replace} aria-label={`Replace (${side})`}
          placeholder={side === 'title' ? 'Ep. => Episode' : '@old_handle => @new_handle'} onChange={(e) => setField(side, 'replace', e.target.value)} />
      </div>
      <div className="form-group" style={{ minWidth: 0, flex: '0 0 auto' }}>
        <label>Add to start</label>
        <input className="form-control" style={input} aria-label={`Add to start (${side})`} value={form[side].prepend} onChange={(e) => setField(side, 'prepend', e.target.value)} />
      </div>
      <div className="form-group" style={{ minWidth: 0, flex: '0 0 auto' }}>
        <label>Add to end</label>
        <input className="form-control" style={input} value={form[side].append} aria-label={`Add to end (${side})`}
          placeholder={side === 'title' ? '| Raat3Baje' : 'Follow us: https://…'} onChange={(e) => setField(side, 'append', e.target.value)} />
      </div>
      {side === 'description' && (
        <div className="form-group" style={{ minWidth: 0, flex: '0 0 auto' }}>
          <label>Added text goes</label>
          <select className="form-control" style={input} aria-label="Added text goes" value={form.separator} onChange={(e) => setForm((f) => ({ ...f, separator: e.target.value }))}>
            <option value={'\n\n'}>after a blank line</option>
            <option value={'\n'}>on a new line</option>
            <option value=" ">on the same line</option>
          </select>
        </div>
      )}
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div className="panel-card">
        <h3 className="panel-title"><PenLine size={20} /> YouTube channels</h3>
        <YouTubeChannels onChange={setYt} />
      </div>

      <div className="panel-card">
        <h3 className="panel-title"><PenLine size={20} /> Bulk edit titles &amp; descriptions</h3>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
          <span style={muted}>Channel</span>
          <select className="form-control" style={{ ...input, width: 'auto', minWidth: 220 }} aria-label="Channel" value={channel} disabled={running || !!busy}
            onChange={(e) => setChannel(e.target.value)}>
            {!signedIn.length && <option value="">— connect a channel above —</option>}
            {signedIn.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
          </select>
          <span style={muted}>Every video on the channel, Shorts included. Preview never changes anything.</span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 24 }}>
          {fieldColumn('title')}
          {fieldColumn('description')}
        </div>

        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginTop: 12 }}>
          <span style={muted}>Only videos that are:</span>
          {['public', 'unlisted', 'private'].map((p) => (
            <label key={p} style={{ ...muted, display: 'inline-flex', gap: 4 }}>
              <input type="checkbox" aria-label={p} checked={form.privacy.includes(p)}
                onChange={(e) => setForm((f) => ({ ...f, privacy: e.target.checked ? [...f.privacy, p] : f.privacy.filter((x) => x !== p) }))} />
              {p}
            </label>
          ))}
          <button type="button" className="btn" disabled={!channel || running || !!busy || !form.privacy.length} onClick={runPreview}>
            {busy === 'preview' ? 'Reading the channel…' : 'Preview changes'}
          </button>
        </div>
        {error && <p style={{ fontSize: '0.82rem', color: '#f87171' }}>{error}</p>}
      </div>

      {preview && (
        <div className="panel-card">
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <b>{preview.items.length} of {preview.total_videos} videos would change</b>
            <button type="button" className="btn btn-outline btn-sm"
              onClick={() => setSelected(new Set(preview.items.filter((i) => !i.problems.length).slice(0, preview.max_per_run).map((i) => i.id)))}>
              Select all
            </button>
            <button type="button" className="btn btn-outline btn-sm" onClick={() => setSelected(new Set())}>Select none</button>
            <span style={muted}>
              {selected.size} selected · {selected.size * 50} quota units of 10,000 a day · max {preview.max_per_run} per run
            </span>
            <button type="button" className="btn" style={{ marginLeft: 'auto' }}
              disabled={!selected.size || selected.size > preview.max_per_run || running}
              onClick={() => setConfirm({ kind: 'apply', count: selected.size, note: `Change ${selected.size} video(s) on ${channelTitle}. The originals are backed up first.` })}>
              Apply to {selected.size} video(s)
            </button>
          </div>
          <div style={{ marginTop: 10, display: 'grid', gap: 8, maxHeight: 560, overflow: 'auto' }}>
            {preview.items.map((i) => (
              <div key={i.id} style={{ padding: 8, borderRadius: 6, border: '1px solid var(--border-color, #333)', fontSize: '0.8rem', opacity: i.problems.length ? 0.7 : 1 }}>
                <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
                  <input type="checkbox" aria-label={`Select ${i.title || i.id}`} disabled={!!i.problems.length} checked={selected.has(i.id)}
                    onChange={(e) => setSelected((s) => { const n = new Set(s); if (e.target.checked) n.add(i.id); else n.delete(i.id); return n; })} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={muted}>{i.privacy} · {i.published_at.slice(0, 10)} · <a href={`https://youtu.be/${i.id}`} target="_blank" rel="noreferrer">{i.id}</a></div>
                    {i.title !== i.new_title ? (
                      <div><s style={{ color: '#f87171' }}>{i.title}</s><br /><span style={{ color: '#22c55e' }}>{i.new_title}</span></div>
                    ) : <div>{i.title}</div>}
                    {i.description !== i.new_description && (
                      <details>
                        <summary style={muted}>Description changes</summary>
                        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                          <pre style={{ flex: 1, minWidth: 220, whiteSpace: 'pre-wrap', color: '#f87171', margin: 0 }}>{i.description}</pre>
                          <pre style={{ flex: 1, minWidth: 220, whiteSpace: 'pre-wrap', color: '#22c55e', margin: 0 }}>{i.new_description}</pre>
                        </div>
                      </details>
                    )}
                    {!!i.problems.length && <div style={{ color: '#f59e0b' }}>Skipped: {i.problems.join('; ')}</div>}
                  </div>
                </label>
              </div>
            ))}
          </div>
        </div>
      )}

      {job && job.state !== 'idle' && (
        <div className="panel-card">
          <b>{job.kind === 'restore' ? 'Restore' : 'Apply'} {job.state === 'running' ? 'running' : 'finished'}:</b>{' '}
          <span style={muted}>{job.done} done, {job.failed} failed of {job.total}{job.backup ? ` · backup ${job.backup}` : ''}</span>
          <progress value={(job.done || 0) + (job.failed || 0)} max={job.total || 1} style={{ width: '100%', marginTop: 6 }} />
          {job.message && <p style={{ fontSize: '0.8rem', color: '#f59e0b' }}>{job.message}</p>}
          <pre style={{ maxHeight: 200, overflow: 'auto', fontSize: '0.74rem', margin: 0 }}>{(job.log || []).join('\n')}</pre>
        </div>
      )}

      <div className="panel-card">
        <b>Restore from a backup</b>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginTop: 8 }}>
          <select className="form-control" style={{ ...input, flex: 1, width: 'auto', minWidth: 0 }} aria-label="Backup to restore" value={backup} onChange={(e) => setBackup(e.target.value)}>
            {!backups.length && <option value="">No backups for this channel yet</option>}
            {backups.map((b) => <option key={b.name} value={b.name}>{b.created_at.replace('T', ' ')} · {b.count} videos · {b.label}</option>)}
          </select>
          <button type="button" className="btn btn-outline" disabled={!backup || running || !!busy} onClick={askRestore}>
            {busy === 'restore' ? 'Checking…' : 'Restore'}
          </button>
        </div>
      </div>

      {confirm && (
        <div role="dialog" aria-modal="true" style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.55)', display: 'grid', placeItems: 'center', zIndex: 50, padding: 16 }}>
          <div className="panel-card" style={{ maxWidth: 440, width: '100%' }}>
            <b>{confirm.kind === 'apply' ? 'Apply changes on YouTube' : 'Restore from backup'}</b>
            <p style={muted}>{confirm.note}</p>
            <div className="form-group">
              <label>Type <b>{confirm.count}</b> to confirm</label>
              <input className="form-control" style={input} aria-label={`Type ${confirm.count} to confirm`} autoFocus inputMode="numeric" value={typed} onChange={(e) => setTyped(e.target.value)} />
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 10 }}>
              <button type="button" className="btn btn-outline" onClick={() => { setConfirm(null); setTyped(''); }}>Cancel</button>
              <button type="button" className="btn" disabled={Number(typed) !== confirm.count} onClick={confirmed}>
                {confirm.kind === 'apply' ? 'Apply' : 'Restore'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
