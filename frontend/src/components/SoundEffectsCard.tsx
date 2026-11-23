import { useEffect, useRef, useState, type ReactNode } from 'react';
import { RefreshCw, Volume2, X } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, putJson, describeError, ApiError } from '../services/api';
import { apiUrl } from '../services/http';
import type { SfxJob, SfxLibraryResponse, SfxLibrarySummary } from '../lib/types';

// Settings "Sound effects" card (BuzzEdit/CLIPS_AND_SOUND_PLAN.md, S4): the
// folders BuzzEdit's sound-effects index scans, kept in sync with BuzzEdit on
// every edit, plus a rescan and an on-demand Stable Audio Open generation.

const SAVE_DEBOUNCE_MS = 700;
const POLL_MS = 1500;

export default function SoundEffectsCard() {
  const { toast } = useStudio();

  const [loaded, setLoaded] = useState(false);
  const [notFound, setNotFound] = useState(false);

  const [dirs, setDirs] = useState<string[]>([]);
  const [defaultDirs, setDefaultDirs] = useState<string[]>([]);
  const [buzzedit, setBuzzedit] = useState<SfxLibrarySummary | null>(null);

  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const dirsRef = useRef<string[]>(dirs);
  const savingRef = useRef(false);
  const pendingRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [rescanning, setRescanning] = useState(false);

  const [genText, setGenText] = useState('');
  const [genKind, setGenKind] = useState<'accent' | 'bed'>('accent');
  const [genSeconds, setGenSeconds] = useState(4);
  const [genJob, setGenJob] = useState<SfxJob | null>(null);
  const [genBusy, setGenBusy] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    dirsRef.current = dirs;
  }, [dirs]);

  const loadLibrary = async () => {
    try {
      const data = await getJson<SfxLibraryResponse>('/api/produce/sfx/library');
      setDirs(data.dirs || []);
      setDefaultDirs(data.default || []);
      setBuzzedit(data.buzzedit);
      setLoaded(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setNotFound(true);
      } else {
        toast(`Could not load the sound-effects library: ${describeError(err)}`, 'error');
      }
    }
  };

  useEffect(() => {
    loadLibrary();
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      if (pollRef.current) clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const flushSave = async () => {
    if (savingRef.current) {
      pendingRef.current = true;
      return;
    }
    savingRef.current = true;
    setSaving(true);
    setSaveError(null);
    const body = { dirs: dirsRef.current.map((d) => d.trim()).filter(Boolean) };
    try {
      const data = await putJson<SfxLibraryResponse>('/api/produce/sfx/library', body);
      setDefaultDirs(data.default || []);
      setBuzzedit(data.buzzedit);
      setDirty(false);
    } catch (err) {
      const msg = describeError(err);
      setSaveError(msg);
      toast(`Could not save the sound-effects folders: ${msg}`, 'error');
    } finally {
      savingRef.current = false;
      setSaving(false);
      if (pendingRef.current) {
        pendingRef.current = false;
        flushSave();
      }
    }
  };

  useEffect(() => {
    if (!dirty) return undefined;
    if (timerRef.current) clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      flushSave();
    }, SAVE_DEBOUNCE_MS);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty, dirs]);

  const flushNow = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (dirty) flushSave();
  };

  const updateRow = (i: number, value: string) => {
    setDirs((prev) => prev.map((d, idx) => (idx === i ? value : d)));
    setDirty(true);
  };
  const removeRow = (i: number) => {
    setDirs((prev) => prev.filter((_, idx) => idx !== i));
    setDirty(true);
  };
  const addRow = () => setDirs((prev) => [...prev, '']);
  const useDefault = () => {
    setDirs([]);
    setDirty(true);
  };

  const rescan = async () => {
    setRescanning(true);
    try {
      const data = await postJson<SfxLibraryResponse>('/api/produce/sfx/library/refresh');
      setDefaultDirs(data.default || []);
      setBuzzedit(data.buzzedit);
      toast('Sound-effects library rescanned.', 'success');
    } catch (err) {
      toast(`Could not rescan the sound-effects library: ${describeError(err)}`, 'error');
    } finally {
      setRescanning(false);
    }
  };

  const onKindChange = (kind: 'accent' | 'bed') => {
    setGenKind(kind);
    setGenSeconds(kind === 'bed' ? 20 : 4);
  };

  const pollJob = (jobId: string) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const job = await getJson<SfxJob>(`/api/produce/sfx/jobs/${encodeURIComponent(jobId)}`);
        setGenJob(job);
        if (job.state === 'done' || job.state === 'failed') {
          if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
          setGenBusy(false);
          if (job.state === 'done') {
            loadLibrary();
          } else {
            setGenError(job.error || 'The effect could not be generated.');
          }
        }
      } catch (err) {
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
        setGenBusy(false);
        setGenError(describeError(err));
      }
    }, POLL_MS);
  };

  const generate = async () => {
    const text = genText.trim();
    if (!text) return;
    setGenBusy(true);
    setGenError(null);
    setGenJob(null);
    try {
      const res = await postJson<{ job_id: string; state: string }>('/api/produce/sfx/generate', {
        text,
        kind: genKind,
        seconds: genSeconds,
      });
      pollJob(res.job_id);
    } catch (err) {
      const msg = describeError(err);
      setGenError(msg);
      toast(`Could not generate the sound effect: ${msg}`, 'error');
      setGenBusy(false);
    }
  };

  if (notFound) {
    return (
      <div className="panel-card">
        <h3 className="panel-title"><Volume2 size={20} /> Sound effects</h3>
        <p style={{ color: '#64748b', fontSize: '0.85rem', margin: 0 }}>
          This Studio backend has no sound-effects routes yet.
        </p>
      </div>
    );
  }

  const topTags = [...(buzzedit?.tags || [])].sort((a, b) => b.count - a.count).slice(0, 12);

  let statusNode: ReactNode = null;
  if (saving) {
    statusNode = <span>Saving…</span>;
  } else if (saveError) {
    statusNode = <span style={{ color: '#f87171' }}>{saveError}</span>;
  } else if (buzzedit) {
    statusNode = <span>Saved · {buzzedit.count} files, {buzzedit.effects} effects, {buzzedit.beds} beds</span>;
  } else if (loaded) {
    statusNode = <span>BuzzEdit is offline — folders are saved here and sent before the next production.</span>;
  }

  return (
    <div className="panel-card">
      <h3 className="panel-title"><Volume2 size={20} /> Sound effects</h3>
      <p style={{ color: '#94a3b8', margin: '0 0 16px 0' }}>
        The folders BuzzEdit searches for the scene's sounds the agents cue (footsteps, a scream, rain). Folder
        names are the tags. An effect the library lacks is generated with Stable Audio Open while the video is
        produced; you can also make one here.
      </p>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 8 }}>
        {dirs.map((d, i) => (
          <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input
              type="text"
              className="form-control"
              style={{ flex: 1 }}
              value={d}
              placeholder="B:\path\to\sound\effects"
              onChange={(e) => updateRow(i, e.target.value)}
              onBlur={flushNow}
              aria-label={`Folder ${i + 1}`}
            />
            <button
              type="button"
              className="btn btn-outline"
              aria-label={`Remove folder ${i + 1}`}
              onClick={() => removeRow(i)}
              style={{ padding: '8px 10px', display: 'inline-flex' }}
            >
              <X size={16} />
            </button>
          </div>
        ))}
      </div>
      {defaultDirs.length > 0 && (
        <p style={{ color: '#64748b', fontSize: '0.78rem', margin: '0 0 10px' }}>Default: {defaultDirs[0]}</p>
      )}
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap', marginBottom: 10 }}>
        <button type="button" className="btn btn-outline" onClick={addRow}>Add folder</button>
        <button type="button" className="btn btn-outline" onClick={useDefault}>Use default</button>
        <button
          type="button"
          className="btn btn-outline"
          disabled={rescanning}
          onClick={rescan}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
        >
          <RefreshCw size={16} className={rescanning ? 'spin' : undefined} />
          {rescanning ? 'Rescanning…' : 'Rescan library'}
        </button>
      </div>
      <p style={{ fontSize: '0.82rem', margin: '0 0 12px', minHeight: '1.2em' }}>{statusNode}</p>

      {topTags.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
          {topTags.map((t) => (
            <span
              key={t.tag}
              style={{
                display: 'inline-flex', alignItems: 'center', fontSize: '0.78rem',
                padding: '3px 10px', borderRadius: 999, border: '1px solid #334155', color: '#94a3b8',
              }}
            >
              {t.tag} · {t.count}
            </span>
          ))}
        </div>
      )}

      {buzzedit?.missing && buzzedit.missing.length > 0 && (
        <p style={{ color: '#facc15', fontSize: '0.8rem', margin: '0 0 12px' }}>
          Not found: {buzzedit.missing.join(', ')}
        </p>
      )}

      <div style={{ borderTop: '1px solid #334155', paddingTop: 16, marginTop: 4 }}>
        <h4 style={{ margin: '0 0 10px', fontSize: '0.95rem', color: '#e2e8f0' }}>Generate a missing effect</h4>
        <div className="form-row">
          <div className="form-group" style={{ flex: '2 1 260px' }}>
            <label>Sound</label>
            <input
              type="text"
              className="form-control"
              placeholder="a woman screams in a corridor"
              value={genText}
              onChange={(e) => setGenText(e.target.value)}
              aria-label="Sound"
            />
          </div>
          <div className="form-group" style={{ flex: '0 0 190px' }}>
            <label>Kind</label>
            <select
              className="form-control"
              value={genKind}
              onChange={(e) => onKindChange(e.target.value as 'accent' | 'bed')}
              aria-label="Kind"
            >
              <option value="accent">Scene sound (accent)</option>
              <option value="bed">Background bed</option>
            </select>
          </div>
          <div className="form-group" style={{ flex: '0 0 110px' }}>
            <label>Seconds</label>
            <input
              type="number"
              className="form-control"
              min={0.5}
              max={47}
              step={0.5}
              value={genSeconds}
              onChange={(e) => setGenSeconds(Math.max(0.5, Math.min(47, Number(e.target.value) || 0.5)))}
              aria-label="Seconds"
            />
          </div>
          <div className="form-group" style={{ flex: '0 0 auto', alignSelf: 'flex-end' }}>
            <button
              type="button"
              className="btn btn-outline"
              disabled={genBusy || !genText.trim()}
              onClick={generate}
            >
              {genBusy ? 'Generating…' : 'Generate'}
            </button>
          </div>
        </div>

        {genBusy && (
          <p style={{ color: '#64748b', fontSize: '0.82rem', margin: '0 0 10px' }}>
            {genJob?.stage || (genJob?.state === 'running' ? 'Generating…' : 'Queued…')}
          </p>
        )}
        {!genBusy && genError && (
          <p style={{ color: '#f87171', fontSize: '0.82rem', margin: '0 0 10px' }}>{genError}</p>
        )}
        {!genBusy && genJob?.state === 'done' && genJob.path && (
          <div style={{ fontSize: '0.82rem', color: '#94a3b8' }}>
            <div style={{ marginBottom: 6 }}>
              Saved to {genJob.path}
              {genJob.duration_s != null ? ` · ${genJob.duration_s.toFixed(1)}s` : ''}
            </div>
            <audio
              controls
              preload="none"
              src={apiUrl(`/api/produce/sfx/file?path=${encodeURIComponent(genJob.path)}`)}
              style={{ height: 32 }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
