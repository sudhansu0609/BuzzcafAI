import { useCallback, useEffect, useRef, useState } from 'react';
import { getJson, postJson, describeError } from '../services/api';

/** Own-footage mode for one project (backend app/api/footage_api.py,
 *  docs/OWN_FOOTAGE_PLAN.md OF4): toggle, footage folder, "Read my clips"
 *  and the clip catalog with notes and Used/Unused after planning. */

type Clip = {
  id: string; name?: string; path?: string; duration?: number; width?: number; height?: number;
  has_audio?: boolean; shot?: number | null; note?: string; error?: string | null;
  description?: { what?: string; place?: string; action?: string; mood?: string; people?: string } | string | null;
};
type FootageState = { footage_dir: string; footage_mode: string; custom_dir: boolean; clips: Clip[] };
type Job = { state: string; message?: string; result?: unknown };

const muted = { color: 'var(--text-secondary)' } as const;

function oneLine(d: Clip['description']): string {
  if (!d) return '';
  if (typeof d === 'string') return d;
  return [d.what, d.action, d.place].filter(Boolean).join('; ');
}

export default function OwnFootage({ projectId, unusedClips, planned, onToast }: {
  projectId: string;
  unusedClips?: string[];
  planned?: boolean;
  onToast: (msg: string, kind?: 'success' | 'error' | 'info') => void;
}) {
  const base = `/api/projects/${encodeURIComponent(projectId)}/footage`;
  const [state, setState] = useState<FootageState | null>(null);
  const [dir, setDir] = useState('');
  const [busy, setBusy] = useState('');
  const [notes, setNotes] = useState<Record<string, string>>({});
  const timer = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const s = await getJson<FootageState>(base);
      setState(s);
      setDir(s.footage_dir || '');
    } catch { /* panel stays empty */ }
  }, [base]);

  useEffect(() => {
    void load();
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [load]);

  const on = state?.footage_mode === 'own';

  const save = async (body: { dir?: string; mode?: string }) => {
    try {
      await postJson(base, body);
      await load();
    } catch (err) {
      onToast(`Could not save own footage settings: ${describeError(err)}`, 'error');
    }
  };

  const scan = async () => {
    try {
      const { job_id } = await postJson<{ job_id: string }>(`${base}/scan`, {});
      setBusy('Starting...');
      if (timer.current) window.clearInterval(timer.current);
      timer.current = window.setInterval(async () => {
        try {
          const job = await getJson<Job>(`/api/footage/jobs/${encodeURIComponent(job_id)}`);
          if (job.state === 'running') { setBusy(job.message || 'Reading...'); return; }
          if (timer.current) window.clearInterval(timer.current);
          timer.current = null;
          setBusy('');
          await load();
          if (job.state === 'done') onToast('Your clips are read.', 'success');
          else onToast(`Reading clips failed: ${job.message || job.state}`, 'error');
        } catch (err) {
          if (timer.current) window.clearInterval(timer.current);
          timer.current = null;
          setBusy('');
          onToast(`Could not follow the clip reading: ${describeError(err)}`, 'error');
        }
      }, 2000);
    } catch (err) {
      setBusy('');
      onToast(`Could not read the clips: ${describeError(err)}`, 'error');
    }
  };

  const saveNote = async (clip: Clip) => {
    const text = notes[clip.id];
    if (text === undefined || text === (clip.note || '')) return;
    try {
      await postJson(`${base}/${encodeURIComponent(clip.id)}/note`, { text });
      await load();
    } catch (err) {
      onToast(`Could not save the note: ${describeError(err)}`, 'error');
    }
  };

  if (!state) return null;
  const clips = state.clips || [];
  const btn = { fontSize: '0.74rem', padding: '3px 10px' } as const;

  return (
    <div style={{ flexBasis: '100%', fontSize: '0.78rem', display: 'flex', flexDirection: 'column', gap: 8,
      padding: '8px 10px', borderRadius: 6, background: 'var(--bg-input, rgba(255,255,255,0.03))' }}>
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
        <b>Own footage</b>
        <label style={{ display: 'flex', gap: 4, alignItems: 'center', cursor: 'pointer' }}>
          <input type="checkbox" checked={on} onChange={(e) => void save({ mode: e.target.checked ? 'own' : '' })} />
          {on ? 'On' : 'Off'}
        </label>
        {on && (
          <span style={{ ...muted, fontSize: '0.72rem' }}>
            Name clips by shot (shot06_notebook.mp4) to pin them; others are matched by what they show. No AI pictures on this project.
          </span>
        )}
      </div>
      {on && (
        <>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={muted}>Folder</span>
            <input type="text" value={dir} onChange={(e) => setDir(e.target.value)}
              style={{ flex: 1, minWidth: 220, fontSize: '0.74rem' }} />
            <button className="btn" style={btn} disabled={!dir.trim() || dir === state.footage_dir}
              onClick={() => void save({ dir })}>Save folder</button>
            <button className="btn" style={btn} disabled={!!busy} onClick={() => void scan()}>Read my clips</button>
            {busy && <span style={muted}>{busy}</span>}
          </div>
          {clips.length === 0 ? (
            <span style={muted}>No clips read yet. Put the clips in the folder and press Read my clips.</span>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {clips.map((c) => {
                const used = planned ? !(unusedClips || []).includes(c.id) : null;
                return (
                  <div key={c.id} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                    <img src={`${base}/${encodeURIComponent(c.id)}/frame`} alt="" loading="lazy"
                      style={{ width: 80, height: 45, objectFit: 'cover', borderRadius: 4, background: '#000' }}
                      onError={(e) => { (e.currentTarget as HTMLImageElement).style.visibility = 'hidden'; }} />
                    <div style={{ flex: 1, minWidth: 200, display: 'flex', flexDirection: 'column', gap: 2 }}>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                        <b>{c.name || c.id}</b>
                        {c.shot != null && (
                          <span style={{ padding: '0 6px', borderRadius: 8, background: 'rgba(167,139,250,0.25)', fontSize: '0.7rem' }}>
                            Shot {c.shot}
                          </span>
                        )}
                        <span style={muted}>{c.duration ? `${c.duration.toFixed(1)} s` : ''}</span>
                        {used !== null && (
                          <span style={{ fontSize: '0.7rem', color: used ? '#34d399' : '#fbbf24' }}>{used ? 'Used' : 'Unused'}</span>
                        )}
                      </div>
                      {c.error ? (
                        <span style={{ color: '#f87171' }}>Could not read: {c.error}</span>
                      ) : (
                        <span style={muted}>{oneLine(c.description) || 'Not described yet.'}</span>
                      )}
                      <input type="text" placeholder="Your note (what it shows, where it fits)"
                        value={notes[c.id] ?? c.note ?? ''}
                        onChange={(e) => setNotes((p) => ({ ...p, [c.id]: e.target.value }))}
                        onBlur={() => void saveNote(c)}
                        style={{ fontSize: '0.72rem' }} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </>
      )}
    </div>
  );
}
