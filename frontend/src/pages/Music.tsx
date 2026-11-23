import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { CheckCircle2, Circle, Download, Loader2, MinusCircle, Music as MusicIcon, RefreshCw, ShieldAlert, ShieldCheck, Sparkles, Trash2, XCircle } from 'lucide-react';
import { useStudio } from '../state/studio';
import { deleteJson, describeError, getJson, postJson } from '../services/api';
import { apiUrl } from '../services/http';
import MusicUpload from '../components/MusicUpload';

/* Background music for the edits, generated locally in ComfyUI via BuzzEdit
 * with one of two engines — ACE-Step (Apache-2.0, full-length beds) or Stable
 * Audio Open (Stability Community licence, loops/stingers up to 47 s) — from a
 * style preset, the genre/instrument/mood/tempo builder, or both. Anything
 * here is what BuzzEdit's music lane may use; a library file with no allowed
 * licence on record is shown flagged and is never put in a video. */

type Style = { name: string; label: string; tags: string; genres: string[]; moods: string[] };
type Engine = { name: string; label: string; model: string; license: string; note: string; max_seconds: number; ready: boolean };
type Raga = { name: string; label: string; time: string; description: string; keyscale: string; bpm: number };
type StylesResponse = {
  styles: Style[]; model_ready: boolean; max_seconds: number; max_variations: number;
  default_engine?: string; engines?: Engine[];
  music_genres?: string[]; instruments?: Record<string, string[]>; moods?: Record<string, string>;
  ragas?: { morning: Raga[]; evening: Raga[] };
  bpm_range?: [number, number]; video_genres?: string[];
  buzzedit_online?: boolean; buzzedit_starting?: boolean; buzzedit_error?: string; builder_supported?: boolean;
};
type Track = {
  file: string; genre: string; style: string; label: string; moods: string[];
  license: string; license_ok: boolean; source: string; seed?: number; seconds?: number; created: string;
  engine?: string; bpm?: number | null; instruments?: string[]; timings?: Record<string, number>;
  measured_bpm?: number | null; onset_rate?: number | null; attempts?: number; passed?: boolean;
};
type Stage = {
  key: string; label: string; group: string; state: 'pending' | 'running' | 'done' | 'failed' | 'skipped';
  progress: number | null; seconds: number | null;
};
type Job = {
  job_id: string; state: 'queued' | 'running' | 'done' | 'failed'; style: string; made: string[]; errors: string[];
  tags?: string; stages?: Stage[]; progress?: number; elapsed?: number;
};
type Preview = { tags: string; dropped: string[]; bpm?: number | null; keyscale?: string | null; engine?: string; caption?: string };

function tempoWord(v: number): string {
  if (v <= 66) return 'very slow';
  if (v <= 85) return 'slow';
  if (v <= 110) return 'medium';
  return 'fast';
}

function fmtSeconds(s: number | null | undefined): string {
  if (s == null) return '—';
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  return `${m}m ${String(Math.round(s % 60)).padStart(2, '0')}s`;
}

function Bar({ value, state }: { value: number; state?: string }) {
  const color = state === 'failed' ? '#f87171' : state === 'done' ? '#34d399' : 'var(--active-menu-border, #a78bfa)';
  return (
    <div style={{ height: 6, borderRadius: 999, background: 'var(--border-subtle, rgba(255,255,255,0.08))', overflow: 'hidden', flex: 1 }}>
      <div style={{ width: `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`, height: '100%', background: color, transition: 'width 0.6s ease' }} />
    </div>
  );
}

const STAGE_ICON = {
  pending: <Circle size={14} style={{ color: 'var(--text-muted)' }} />,
  running: <Loader2 size={14} className="spin" style={{ color: 'var(--active-menu-border, #a78bfa)' }} />,
  done: <CheckCircle2 size={14} style={{ color: '#34d399' }} />,
  failed: <XCircle size={14} style={{ color: '#f87171' }} />,
  skipped: <MinusCircle size={14} style={{ color: 'var(--text-muted)' }} />,
};

/** Overall bar, each stage with its own bar and time, then time per stage kind. */
function JobProgress({ job }: { job: Job }) {
  const stages = job.stages ?? [];
  const totals = new Map<string, number>();
  for (const st of stages) {
    if (st.seconds != null && st.state !== 'pending' && st.state !== 'skipped') {
      totals.set(st.label, (totals.get(st.label) ?? 0) + st.seconds);
    }
  }
  let lastGroup = '';
  return (
    <div style={{ marginTop: 18, padding: 14, borderRadius: 10, border: '1px solid var(--border-card, rgba(255,255,255,0.12))' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 6 }}>
        <strong style={{ fontSize: '0.9rem' }}>
          {job.state === 'done' ? 'Finished' : job.state === 'failed' ? 'Failed' : job.state === 'queued' ? 'Queued' : 'Generating'}
        </strong>
        <Bar value={job.progress ?? 0} state={job.state} />
        <span style={{ fontSize: '0.82rem', width: 44, textAlign: 'right' }}>{Math.round((job.progress ?? 0) * 100)}%</span>
        <span style={{ fontSize: '0.82rem', color: 'var(--text-muted)', width: 70, textAlign: 'right' }}>{fmtSeconds(job.elapsed)}</span>
      </div>
      {job.tags && <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)', marginBottom: 10 }}>Prompt: {job.tags}</div>}
      <div style={{ display: 'grid', gridTemplateColumns: '18px minmax(150px, 220px) 1fr 70px', gap: '6px 10px', alignItems: 'center', fontSize: '0.82rem' }}>
        {stages.map((st) => {
          const header = st.group && st.group !== lastGroup ? st.group : '';
          lastGroup = st.group || lastGroup;
          const value = st.state === 'done' ? 1 : st.progress ?? (st.state === 'running' ? 0.04 : 0);
          const idle = st.state === 'pending' || st.state === 'skipped';
          return (
            <div key={st.key} style={{ display: 'contents' }}>
              {header && <div style={{ gridColumn: '1 / -1', fontSize: '0.74rem', fontWeight: 600, color: 'var(--text-muted)', marginTop: 4 }}>{header}</div>}
              {STAGE_ICON[st.state]}
              <span style={{ color: idle ? 'var(--text-muted)' : 'var(--text-primary)' }}>
                {st.label}
                {st.state === 'running' && st.progress != null && st.progress < 1 ? ` · ${Math.round(st.progress * 100)}%` : ''}
                {st.state === 'skipped' ? ' (skipped)' : ''}
              </span>
              <Bar value={value} state={st.state} />
              <span style={{ textAlign: 'right', color: 'var(--text-muted)' }}>{idle ? '—' : fmtSeconds(st.seconds)}</span>
            </div>
          );
        })}
      </div>
      {totals.size > 0 && (
        <div style={{ marginTop: 12, paddingTop: 10, borderTop: '1px solid var(--border-subtle, rgba(255,255,255,0.08))' }}>
          <div style={{ fontSize: '0.74rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.04em' }}>Time taken</div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 18px', fontSize: '0.82rem' }}>
            {[...totals.entries()].map(([label, secs]) => (
              <span key={label}>{label}: <strong>{fmtSeconds(secs)}</strong></span>
            ))}
            <span>Total: <strong>{fmtSeconds(job.elapsed)}</strong></span>
          </div>
        </div>
      )}
      {job.errors.length > 0 && (
        <div style={{ color: '#f87171', fontSize: '0.8rem', marginTop: 8 }}>{job.errors.join(' · ')}</div>
      )}
    </div>
  );
}

function Chip({ on, onClick, children, title }: { on: boolean; onClick: () => void; children: ReactNode; title?: string }) {
  return (
    <button type="button" onClick={onClick} title={title} aria-pressed={on}
      style={{
        padding: '4px 11px', borderRadius: 999, cursor: 'pointer', fontSize: '0.8rem',
        border: `1px solid ${on ? 'var(--active-menu-border, #a78bfa)' : 'var(--border-card, rgba(255,255,255,0.12))'}`,
        background: on ? 'var(--active-menu-bg, rgba(167,139,250,0.18))' : 'transparent',
        color: on ? 'var(--text-primary)' : 'var(--text-secondary)',
      }}>
      {children}
    </button>
  );
}

const sectionLabel: CSSProperties = {
  fontSize: '0.78rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.04em',
  color: 'var(--text-muted)', margin: '14px 0 8px',
};
const chipRow: CSSProperties = { display: 'flex', flexWrap: 'wrap', gap: 6 };

const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

export default function Music() {
  const { toast } = useStudio();
  const [styles, setStyles] = useState<StylesResponse | null>(null);
  const [tracks, setTracks] = useState<Track[]>([]);
  const [loadError, setLoadError] = useState('');
  // Empty until the styles arrive: the server names the default engine. Only an
  // engine the creator picked by hand survives a reload -- starting on 'ace_step'
  // kept every session on ACE-Step v1, which has no real tempo control.
  const [engine, setEngine] = useState('');
  const engineChosen = useRef(false);
  const [style, setStyle] = useState('');
  const [musicGenres, setMusicGenres] = useState<string[]>([]);
  const [instruments, setInstruments] = useState<string[]>([]);
  const [moods, setMoods] = useState<string[]>([]);
  const [raga, setRaga] = useState<string | null>(null);
  const [bpm, setBpm] = useState<number | null>(null);
  const [variations, setVariations] = useState(2);
  const [seconds, setSeconds] = useState(120);
  const [extraTags, setExtraTags] = useState('');
  const [forGenre, setForGenre] = useState('');
  const [job, setJob] = useState<Job | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [filter, setFilter] = useState('');
  const pollRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const [s, lib] = await Promise.all([
        getJson<StylesResponse>('/api/music/styles'),
        getJson<{ tracks: Track[] }>('/api/music/library'),
      ]);
      setStyles(s);
      setTracks(lib.tracks || []);
      if (s.default_engine) setEngine((cur) => (engineChosen.current && s.engines?.some((e) => e.name === cur)
        ? cur : s.default_engine!));
      setLoadError('');
    } catch (err) {
      setLoadError(describeError(err));
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  // The Studio starts BuzzEdit when it is down; keep asking until it answers.
  const offline = styles !== null && styles.buzzedit_online === false;
  useEffect(() => {
    if (!offline) return;
    const t = window.setInterval(load, 4000);
    return () => window.clearInterval(t);
  }, [offline, load]);
  useEffect(() => () => { if (pollRef.current) window.clearInterval(pollRef.current); }, []);

  const engines = styles?.engines ?? [];
  const currentEngine = engines.find((e) => e.name === engine);
  const maxSeconds = currentEngine?.max_seconds ?? styles?.max_seconds ?? 240;
  const minSeconds = Math.min(30, maxSeconds);
  const lengthSeconds = Math.min(seconds, maxSeconds);
  const engineReady = currentEngine ? currentEngine.ready : !!styles?.model_ready;
  const [bpmMin, bpmMax] = styles?.bpm_range ?? [50, 180];
  const ragaMorning = styles?.ragas?.morning ?? [];
  const ragaEvening = styles?.ragas?.evening ?? [];
  const selectedRaga = [...ragaMorning, ...ragaEvening].find((r) => r.name === raga);
  const hasRecipe = !!style || !!raga || musicGenres.length + instruments.length + moods.length > 0 || !!extraTags.trim();

  // BuzzEdit composes the prompt; ask it, so the preview is exactly what runs.
  useEffect(() => {
    if (!hasRecipe || offline) { setPreview(null); return; }
    const t = window.setTimeout(async () => {
      try {
        setPreview(await postJson<Preview>('/api/music/preview', {
          engine: engine || undefined, style: style || null, music_genres: musicGenres, instruments, moods, bpm, extra_tags: extraTags,
          raga: raga || null,
        }));
      } catch { setPreview(null); }
    }, 300);
    return () => window.clearTimeout(t);
  }, [hasRecipe, offline, engine, style, musicGenres, instruments, moods, bpm, extraTags, raga]);

  const removeTrack = async (t: Track) => {
    if (!window.confirm(`Delete "${t.label}" (${t.file}) from the music library? This cannot be undone.`)) return;
    try {
      await deleteJson(`/api/music/file/${t.file.split('/').map(encodeURIComponent).join('/')}`);
      setTracks((cur) => cur.filter((x) => x.file !== t.file));
      toast(`Deleted ${t.file}`, 'success');
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const reset = () => { setStyle(''); setMusicGenres([]); setInstruments([]); setMoods([]); setRaga(null); setBpm(null); setExtraTags(''); };

  const generate = async () => {
    try {
      const started = await postJson<Job>('/api/music/generate', {
        engine: engine || undefined, style: style || null, music_genres: musicGenres, instruments, moods, bpm,
        variations, seconds: lengthSeconds, extra_tags: extraTags, genre: forGenre || null,
        raga: raga || null,
      });
      setJob(started);
      if (pollRef.current) window.clearInterval(pollRef.current);
      pollRef.current = window.setInterval(async () => {
        try {
          const j = await getJson<Job>(`/api/music/jobs/${started.job_id}`);
          setJob(j);
          if (j.state === 'done' || j.state === 'failed') {
            if (pollRef.current) window.clearInterval(pollRef.current);
            pollRef.current = null;
            if (j.state === 'done' && j.made.length) toast(`${j.made.length} track(s) added to the library.`, 'success');
            else toast(`Music generation ${j.state}: ${j.errors[0] || 'no audio produced'}`, 'error');
            load();
          }
        } catch { /* transient; keep polling */ }
      }, 1500);
    } catch (err) {
      toast(describeError(err), 'error');
    }
  };

  const busy = job?.state === 'queued' || job?.state === 'running';
  const shown = useMemo(
    () => tracks.filter((t) => !filter || t.style === filter || t.genre === filter || t.engine === filter),
    [tracks, filter],
  );

  return (
    <div>
      <div className="panel-card" style={{ marginBottom: 24 }}>
        <h3 className="panel-title"><MusicIcon size={22} /> Generate music</h3>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.88rem', marginTop: 0 }}>
          Instrumental beds made on your GPU. Start from a style preset, build your own from genre, instruments,
          mood and tempo, or combine both. Each variation is a new seed; every track lands in BuzzEdit's music
          library, where the edit picks it up by genre and mood. While it runs, other models are ejected from the
          GPU, and all models are offloaded when it finishes.
        </p>
        {loadError && (
          <div style={{ color: '#f87171', fontSize: '0.85rem', marginBottom: 12 }}>
            {loadError}
          </div>
        )}
        {offline && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: styles?.buzzedit_error ? '#f87171' : '#fbbf24', fontSize: '0.85rem', marginBottom: 12 }}>
            {styles?.buzzedit_error
              ? <>BuzzEdit could not be started: {styles.buzzedit_error}</>
              : <><Loader2 size={14} className="spin" /> Starting BuzzEdit (and ComfyUI)… you can set up the track meanwhile.</>}
          </div>
        )}
        {styles?.buzzedit_online && styles.builder_supported === false && (
          <div style={{ color: '#fbbf24', fontSize: '0.85rem', marginBottom: 12 }}>
            This BuzzEdit is running an older build without the engine/builder options — restart BuzzEdit to use them.
          </div>
        )}

        {engines.length > 0 && (
          <>
            <div style={sectionLabel}>Engine</div>
            <div role="radiogroup" style={{ display: 'inline-flex', border: '1px solid var(--border-card, rgba(255,255,255,0.12))', borderRadius: 10, overflow: 'hidden' }}>
              {engines.map((e) => (
                <button key={e.name} type="button" role="radio" aria-checked={engine === e.name}
                  onClick={() => { engineChosen.current = true; setEngine(e.name); }} title={`${e.model} · ${e.license}`}
                  style={{
                    padding: '8px 16px', cursor: 'pointer', border: 'none', fontSize: '0.86rem', fontWeight: 600,
                    background: engine === e.name ? 'var(--active-menu-bg, rgba(167,139,250,0.22))' : 'transparent',
                    color: engine === e.name ? 'var(--text-primary)' : 'var(--text-secondary)',
                  }}>
                  {e.label}{!e.ready && ' (not set up)'}
                </button>
              ))}
            </div>
            {currentEngine && (
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 6 }}>
                {currentEngine.model} · {currentEngine.license} — {currentEngine.note}
              </div>
            )}
          </>
        )}
        {styles && !offline && !engineReady && (
          <div style={{ color: '#fbbf24', fontSize: '0.85rem', marginTop: 10 }}>
            The {currentEngine?.label ?? 'ACE-Step'} workflow is not configured in BuzzEdit yet.
          </div>
        )}

        <div style={{ ...sectionLabel, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span>Style preset <span style={{ textTransform: 'none', fontWeight: 400 }}>(optional — click again to clear)</span></span>
          {hasRecipe && <button type="button" className="btn btn-outline" onClick={reset} style={{ padding: '2px 10px', fontSize: '0.75rem' }}>Reset</button>}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(190px, 1fr))', gap: 10 }}>
          {styles?.styles.map((s) => (
            <button
              key={s.name}
              type="button"
              onClick={() => {
                const next = style === s.name ? '' : s.name;
                setStyle(next);
                const m = next ? /^(morning|evening)_raga_/.exec(next) : null;
                if (m) {
                  const group = m[1] === 'morning' ? ragaMorning : ragaEvening;
                  if (group[0]) setRaga(group[0].name);
                }
              }}
              title={s.tags}
              style={{
                textAlign: 'left', padding: '10px 12px', borderRadius: 8, cursor: 'pointer',
                border: `1px solid ${style === s.name ? 'var(--active-menu-border, #a78bfa)' : 'var(--border-card, rgba(255,255,255,0.12))'}`,
                background: style === s.name ? 'var(--active-menu-bg, rgba(167,139,250,0.12))' : 'var(--bg-card, transparent)',
                color: 'var(--text-primary)',
              }}
            >
              <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>{s.label}</div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.74rem', marginTop: 4 }}>{s.moods.join(' · ')}</div>
            </button>
          ))}
        </div>

        {styles?.music_genres && (
          <>
            <div style={sectionLabel}>Genre</div>
            <div style={chipRow}>
              {styles.music_genres.map((g) => (
                <Chip key={g} on={musicGenres.includes(g)} onClick={() => setMusicGenres((l) => toggle(l, g))}>{g}</Chip>
              ))}
            </div>
          </>
        )}

        {styles?.instruments && (
          <>
            <div style={sectionLabel}>Classical <span style={{ textTransform: 'none', fontWeight: 400 }}>(quick pick)</span></div>
            <div style={chipRow}>
              {['bansuri flute', 'violin', 'sitar'].map((i) => (
                <Chip key={`classical-${i}`} on={instruments.includes(i)} onClick={() => setInstruments((l) => toggle(l, i))}>{i}</Chip>
              ))}
            </div>
          </>
        )}

        {styles?.instruments && (
          <>
            <div style={sectionLabel}>Instruments</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {Object.entries(styles.instruments).map(([group, items]) => (
                <div key={group} style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: '0.76rem', color: 'var(--text-muted)', width: 92, flexShrink: 0 }}>{group}</span>
                  <div style={{ ...chipRow, flex: 1 }}>
                    {items.map((i) => (
                      <Chip key={i} on={instruments.includes(i)} onClick={() => setInstruments((l) => toggle(l, i))}>{i}</Chip>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        {styles?.moods && (
          <>
            <div style={sectionLabel}>Mood</div>
            <div style={chipRow}>
              {Object.entries(styles.moods).map(([m, act]) => (
                <Chip key={m} on={moods.includes(m)} onClick={() => setMoods((l) => toggle(l, m))}
                  title={`Filed as "${act}" so the edit uses it in ${act} acts`}>{m}</Chip>
              ))}
            </div>
          </>
        )}

        {(ragaMorning.length > 0 || ragaEvening.length > 0) && (
          <>
            <div style={sectionLabel}>Raga <span style={{ textTransform: 'none', fontWeight: 400 }}>(optional — click again to clear)</span></div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {ragaMorning.length > 0 && (
                <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: '0.76rem', color: 'var(--text-muted)', width: 92, flexShrink: 0 }}>Morning</span>
                  <div style={{ ...chipRow, flex: 1 }}>
                    {ragaMorning.map((r) => (
                      <Chip key={r.name} on={raga === r.name} onClick={() => setRaga((cur) => (cur === r.name ? null : r.name))}
                        title={`${r.description} (default ~${r.bpm} bpm, ${r.keyscale})`}>{r.label}</Chip>
                    ))}
                  </div>
                </div>
              )}
              {ragaEvening.length > 0 && (
                <div style={{ display: 'flex', gap: 10, alignItems: 'baseline', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: '0.76rem', color: 'var(--text-muted)', width: 92, flexShrink: 0 }}>Evening</span>
                  <div style={{ ...chipRow, flex: 1 }}>
                    {ragaEvening.map((r) => (
                      <Chip key={r.name} on={raga === r.name} onClick={() => setRaga((cur) => (cur === r.name ? null : r.name))}
                        title={`${r.description} (default ~${r.bpm} bpm, ${r.keyscale})`}>{r.label}</Chip>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </>
        )}

        <div style={{ display: 'flex', gap: 22, flexWrap: 'wrap', alignItems: 'center', marginTop: 16 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem' }}>
            <input type="checkbox" aria-label="Tempo (speed)" checked={bpm !== null}
              onChange={(e) => setBpm(e.target.checked ? (selectedRaga?.bpm ?? 90) : null)} />
            Tempo (speed)
            <input type="range" aria-label="Tempo (bpm)" min={bpmMin} max={bpmMax} step={1} value={bpm ?? (selectedRaga?.bpm ?? 90)} disabled={bpm === null}
              onChange={(e) => setBpm(Number(e.target.value))} />
            <span style={{ minWidth: 64, color: bpm === null ? 'var(--text-muted)' : undefined }}>
              {bpm === null
                ? (selectedRaga ? `auto (raga ~${selectedRaga.bpm} bpm)` : 'auto')
                : `${bpm} bpm · ${tempoWord(bpm)}`}
            </span>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem' }}>
            Length
            <input type="range" aria-label="Length" min={minSeconds} max={maxSeconds} step={maxSeconds <= 60 ? 1 : 10} value={lengthSeconds}
              onChange={(e) => setSeconds(Number(e.target.value))} />
            <span style={{ width: 44 }}>{lengthSeconds}s</span>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem' }}
            title="Which videos' library folder the track goes in -- the edit looks there first, by act mood.">
            For videos of
            <select className="form-control" aria-label="For videos of" value={forGenre} onChange={(e) => setForGenre(e.target.value)} style={{ width: 170 }}>
              <option value="">{style ? "Preset's genres" : 'General (any video)'}</option>
              {(styles?.video_genres ?? []).map((g) => <option key={g} value={g}>{g.replace(/_/g, ' ')}</option>)}
            </select>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.85rem' }}>
            Variations
            <input type="number" className="form-control" aria-label="Variations" min={1} max={styles?.max_variations ?? 6} value={variations}
              onChange={(e) => setVariations(Math.max(1, Math.min(styles?.max_variations ?? 6, Number(e.target.value) || 1)))}
              style={{ width: 70 }} />
          </label>
        </div>

        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'center', marginTop: 14 }}>
          <input className="form-control" aria-label="Extra tags" placeholder="Extra tags (optional), e.g. rain, monsoon, slow build"
            value={extraTags} onChange={(e) => setExtraTags(e.target.value)} style={{ flex: 1, minWidth: 220 }} />
          <button type="button" className="btn" disabled={!hasRecipe || busy || (!offline && !engineReady)} onClick={generate}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            {busy ? <Loader2 size={15} className="spin" /> : <Sparkles size={15} />}
            <span>{busy ? `Generating (${job?.state})…` : 'Generate'}</span>
          </button>
        </div>

        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: 12 }}>
          <strong style={{ color: 'var(--text-secondary)' }}>Prompt:</strong>{' '}
          {!hasRecipe ? 'pick a preset, a raga, or at least one genre, instrument or mood.'
            : preview ? preview.tags : offline ? 'shown once BuzzEdit is up.' : '…'}
          {preview && preview.dropped.length > 0 && (
            <div style={{ marginTop: 4 }}>
              <strong style={{ color: 'var(--text-secondary)' }}>Left out of the preset</strong> (your picks override them): {preview.dropped.join(', ')}
            </div>
          )}
          {preview?.caption && <div style={{ marginTop: 4 }}>{preview.caption}</div>}
          {preview && (preview.bpm != null || preview.keyscale) && (
            <div style={{ marginTop: 4 }}>
              {preview.bpm != null && <>Tempo: <strong>{preview.bpm} bpm</strong> · {tempoWord(preview.bpm)}</>}
              {preview.bpm != null && preview.keyscale ? ' · ' : ''}
              {preview.keyscale && <>Key: <strong>{preview.keyscale}</strong></>}
            </div>
          )}
        </div>

        {job && <JobProgress job={job} />}
      </div>

      <div className="panel-card">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
          <h3 className="panel-title" style={{ margin: 0 }}>Music library ({shown.length})</h3>
          <div style={{ display: 'flex', gap: 8 }}>
            <select className="form-control" aria-label="Filter tracks" value={filter} onChange={(e) => setFilter(e.target.value)} style={{ width: 200 }}>
              <option value="">All styles & genres</option>
              {styles?.styles.map((s) => <option key={s.name} value={s.name}>{s.label}</option>)}
              {[...new Set(tracks.map((t) => t.genre).filter(Boolean))].map((g) => <option key={`g-${g}`} value={g}>Genre: {g}</option>)}
              {engines.map((e) => <option key={`e-${e.name}`} value={e.name}>Engine: {e.label}</option>)}
            </select>
            <button type="button" className="btn btn-outline" onClick={load} title="Refresh" aria-label="Refresh"><RefreshCw size={15} /></button>
          </div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 12 }}>
          <MusicUpload onUploaded={load} onToast={toast} />
          <div style={{ color: 'var(--text-muted)', fontSize: '0.74rem' }}>
            Your own tracks go in <code>uploads/</code>, evened out to the same loudness as the generated ones. They are
            only used where you pick them (a project's <em>Music → Your tracks</em>), at the level you set there.
          </div>
        </div>
        {shown.length === 0 ? (
          <div style={{ color: 'var(--text-muted)', padding: 20, textAlign: 'center' }}>No tracks yet — generate some above, or add your own.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {shown.map((t) => {
              const bpmText = t.bpm == null ? '' : (t.measured_bpm != null
                ? `asked ${t.bpm} bpm, came out ${Math.round(t.measured_bpm)} bpm`
                : `${t.bpm} bpm`);
              const tempoBadge = t.attempts == null ? '' : (t.passed
                ? 'matched'
                : `closest of ${t.attempts} ${t.attempts === 1 ? 'try' : 'tries'}`);
              return (
              <div key={t.file} style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap', padding: '10px 12px', border: '1px solid var(--border-subtle, rgba(255,255,255,0.08))', borderRadius: 8 }}>
                <div style={{ minWidth: 200, flex: 1 }}>
                  <div style={{ fontWeight: 600 }}>
                    {t.label}{t.seed ? <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}> · seed {t.seed}</span> : null}
                    {tempoBadge && (
                      <span title={t.attempts != null ? `${t.attempts} take(s) tried to match the asked tempo` : undefined}
                        style={{
                          marginLeft: 8, display: 'inline-flex', alignItems: 'center', fontSize: '0.68rem', padding: '1px 7px',
                          borderRadius: 999, color: t.passed ? '#34d399' : '#fbbf24',
                          border: `1px solid ${t.passed ? 'rgba(52,211,153,0.4)' : 'rgba(251,191,36,0.4)'}`,
                        }}>{tempoBadge}</span>
                    )}
                  </div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.76rem' }}>
                    {t.genre || 'library'} · {t.moods.join(', ') || 'no mood tags'}{t.seconds ? ` · ${Math.round(t.seconds)}s` : ''}
                    {bpmText ? ` · ${bpmText}` : ''}
                    {t.engine ? ` · ${engines.find((e) => e.name === t.engine)?.label ?? t.engine}` : ''}
                    {t.instruments?.length ? ` · ${t.instruments.join(', ')}` : ''}
                  </div>
                  {t.timings && t.timings.total != null && (
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.72rem', marginTop: 2 }}>
                      Made in {fmtSeconds(t.timings.total)}
                      {['load', 'sample', 'decode', 'master'].filter((k) => t.timings![k] != null)
                        .map((k) => ` · ${k} ${fmtSeconds(t.timings![k])}`).join('')}
                    </div>
                  )}
                </div>
                <span
                  title={t.source || (t.license_ok ? '' : 'Add an allowed "license" to this file\'s manifest.json, or it will not be used.')}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: '0.74rem', padding: '2px 8px', borderRadius: 999,
                    color: t.license_ok ? '#34d399' : '#f87171',
                    border: `1px solid ${t.license_ok ? 'rgba(52,211,153,0.4)' : 'rgba(248,113,113,0.4)'}`,
                  }}
                >
                  {t.license_ok ? <ShieldCheck size={12} /> : <ShieldAlert size={12} />}
                  {t.license_ok ? t.license : 'no licence — not used'}
                </span>
                <audio controls preload="none" src={apiUrl(`/api/music/file/${t.file.split('/').map(encodeURIComponent).join('/')}`)} style={{ height: 34 }} />
                <a className="btn btn-outline" title="Save a copy to your computer"
                  href={apiUrl(`/api/music/file/${t.file.split('/').map(encodeURIComponent).join('/')}?download=1`)}
                  download={t.file.split('/').pop()}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '5px 10px', fontSize: '0.8rem' }}>
                  <Download size={14} /> Save
                </a>
                <button type="button" className="btn btn-outline" title="Delete from the music library" onClick={() => removeTrack(t)}
                  style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '5px 10px', fontSize: '0.8rem', color: '#f87171' }}>
                  <Trash2 size={14} /> Delete
                </button>
              </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
