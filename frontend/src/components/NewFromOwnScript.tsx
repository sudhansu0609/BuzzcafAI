import { useRef, useState, type ChangeEvent, type FormEvent } from 'react';
import { FileText, UploadCloud, X } from 'lucide-react';
import { useStudio } from '../state/studio';
import { postJson, describeError } from '../services/api';
import { CHANNEL_META, workflowFor } from '../lib/channels';

/** A new project from the creator's own script, on the Projects page.
 *  The backend (`own_script` on POST /api/projects -> engine.use_own_script)
 *  skips research and every writing/rewrite step; his words go on as written. */
export default function NewFromOwnScript({ onClose }: { onClose: () => void }) {
  const { brands, refreshProjects, toast, channelFilter, selectedChannel } = useStudio();
  const brandOptions = brands.length > 0 ? brands : CHANNEL_META.map((c) => c.id);
  const [name, setName] = useState('');
  const [brand, setBrand] = useState(channelFilter || selectedChannel || 'Raat3Baje');
  const [script, setScript] = useState('');
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const words = script.trim() ? script.trim().split(/\s+/).length : 0;
  // ~140 spoken words a minute, the same pace the long-script budgets use.
  const minutes = words ? Math.max(1, Math.round(words / 140)) : 0;

  const loadFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    try {
      setScript(await file.text());
      if (!name.trim()) setName(file.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim());
    } catch (err) {
      toast(`Could not read ${file.name}: ${describeError(err)}`, 'error');
    }
  };

  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !script.trim() || busy) return;
    setBusy(true);
    try {
      await postJson('/api/projects', {
        name: name.trim(),
        brand,
        workflow_name: workflowFor(brand),
        own_script: script.trim(),
        ...(minutes ? { target_duration_minutes: minutes } : {}),
      });
      toast(`"${name.trim()}" created from your script. Research and writing are skipped.`, 'success');
      setName('');
      setScript('');
      await refreshProjects();
      onClose();
    } catch (err) {
      toast(`Could not create the project: ${describeError(err)}`, 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <form className="card" onSubmit={create} style={{ marginBottom: 16, padding: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600 }}>
          <FileText size={16} />
          <span>New project from my script</span>
        </div>
        <button type="button" className="btn btn-outline" onClick={onClose} aria-label="Close">
          <X size={14} />
        </button>
      </div>
      <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: 12 }}>
        Research, script writing and every rewrite are skipped -- your words are used exactly as written.
        The project goes on from the visual plan and SEO.
      </div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        <div className="form-group" style={{ flex: '2 1 240px', margin: 0 }}>
          <label>Title</label>
          <input className="form-control" value={name} onChange={(e) => setName(e.target.value)} placeholder="Episode title" />
        </div>
        <div className="form-group" style={{ flex: '1 1 160px', margin: 0 }}>
          <label>Channel</label>
          <select className="form-control" value={brand} onChange={(e) => setBrand(e.target.value)}>
            {brandOptions.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        </div>
      </div>
      <div className="form-group" style={{ marginBottom: 8 }}>
        <label>Script</label>
        <textarea
          className="form-control"
          rows={12}
          aria-label="Your script"
          placeholder="Paste your script here, or load a .txt / .md file"
          value={script}
          onChange={(e) => setScript(e.target.value)}
        />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <button type="submit" className="btn" disabled={busy || !name.trim() || !script.trim()}>
          <span>{busy ? 'Creating…' : 'Create project'}</span>
        </button>
        <button type="button" className="btn btn-outline" onClick={() => fileRef.current?.click()}>
          <UploadCloud size={14} />
          <span>Load file</span>
        </button>
        <input ref={fileRef} type="file" accept=".txt,.md,.markdown,text/plain,text/markdown" hidden onChange={loadFile} />
        {words > 0 && (
          <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
            {words.toLocaleString()} words · about {minutes} min
          </span>
        )}
      </div>
    </form>
  );
}
