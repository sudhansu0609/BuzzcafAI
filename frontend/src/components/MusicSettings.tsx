import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { getJson } from '../services/api';
import { apiUrl } from '../services/http';
import MusicUpload from './MusicUpload';

/* A project's background music: on/off, whether the script's [music: ...]
 * cues (written by the planner agents) are followed, the engine new tracks are
 * made with, and an optional brief for the whole video. The brief uses
 * BuzzEdit's cue grammar -- "style=...; instruments=...; mood=...; bpm=..." --
 * so it means exactly what a cue in the script would.
 *
 * "Your tracks" overrides all of that: library tracks the creator picks (or
 * adds right here), each at a fixed level in dB and optionally ducked under
 * the voice, played together or one after another. */

type Catalog = {
  styles: { name: string; label: string }[];
  engines?: { name: string; label: string; max_seconds: number }[];
  instruments?: Record<string, string[]>;
  moods?: Record<string, string>;
};

let catalogCache: Catalog | null = null;

export type PickedTrack = { file: string; volume_db: number; duck: boolean };
type LibraryTrack = { file: string; label: string; genre: string; license_ok: boolean; seconds?: number | null };

const DB_MIN = -40;
const DB_MAX = 6;
const DEFAULT_DB = -20;
const trackUrl = (file: string) => apiUrl(`/api/music/file/${file.split('/').map(encodeURIComponent).join('/')}`);

type Brief = { style: string; instruments: string[]; mood: string; bpm: string; text: string };

/** "style=a; instruments=b,c; mood=d; bpm=70" -> fields; free text stays text. */
function parseBrief(brief: string): Brief {
  const out: Brief = { style: '', instruments: [], mood: '', bpm: '', text: '' };
  if (!brief.includes('=')) return { ...out, text: brief };
  for (const part of brief.split(/[;|]/)) {
    const [k, ...rest] = part.split('=');
    const key = (k || '').trim().toLowerCase();
    const value = rest.join('=').trim();
    if (key === 'style' || key === 'preset') out.style = value;
    else if (key.startsWith('instrument')) out.instruments = value.split(',').map((v) => v.trim()).filter(Boolean);
    else if (key.startsWith('mood')) out.mood = value.split(',')[0].trim();
    else if (key === 'bpm' || key === 'tempo') out.bpm = value;
    else if (key === 'tags' || key === 'extra') out.text = value;
  }
  return out;
}

function serializeBrief(b: Brief): string {
  const parts: string[] = [];
  if (b.style) parts.push(`style=${b.style}`);
  if (b.instruments.length) parts.push(`instruments=${b.instruments.join(',')}`);
  if (b.mood) parts.push(`mood=${b.mood}`);
  if (b.bpm) parts.push(`bpm=${b.bpm}`);
  if (b.text.trim()) parts.push(`tags=${b.text.trim()}`);
  return parts.join('; ');
}

/** A picked track's preview player, played at the level its slider is set to,
 * so moving the slider is heard while it plays. A cut is the element's own
 * volume; a boost above 0 dB needs a Web Audio gain, which can only read a
 * same-origin file, so a cross-origin one stays at full volume above 0 dB. */
function TrackPreview({ src, db }: { src: string; db: number }) {
  const ref = useRef<HTMLAudioElement>(null);
  const boost = useRef<{ ctx: AudioContext; gain: GainNode } | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const linear = Math.pow(10, db / 20);
    el.volume = Math.max(0, Math.min(1, linear));
    let sameOrigin = false;
    try { sameOrigin = new URL(src, window.location.href).origin === window.location.origin; } catch { /* no boost */ }
    if (linear > 1 && !boost.current && sameOrigin && typeof AudioContext !== 'undefined') {
      try {
        const ctx = new AudioContext();
        const gain = ctx.createGain();
        ctx.createMediaElementSource(el).connect(gain).connect(ctx.destination);
        boost.current = { ctx, gain };
      } catch { /* the element plays on at full volume */ }
    }
    if (boost.current) boost.current.gain.gain.value = Math.max(1, linear);
  }, [db, src]);
  useEffect(() => () => { boost.current?.ctx.close().catch(() => undefined); }, []);
  return (
    <audio ref={ref} controls preload="none" src={src} style={{ height: 30, width: 200 }}
      onPlay={() => { boost.current?.ctx.resume().catch(() => undefined); }} />
  );
}

type Props = {
  music: boolean;
  musicCues: boolean;
  engine: string;
  brief: string;
  tracks: PickedTrack[];
  tracksMode: string;
  disabled?: boolean;
  onPatch: (patch: Record<string, unknown>) => void;
  onToast: (text: string, kind?: 'success' | 'error' | 'info') => void;
};

export default function MusicSettings({ music, musicCues, engine, brief, tracks, tracksMode, disabled, onPatch, onToast }: Props) {
  const [catalog, setCatalog] = useState<Catalog | null>(catalogCache);
  const [draft, setDraft] = useState<Brief>(() => parseBrief(brief));
  const [picked, setPicked] = useState<PickedTrack[]>(tracks);
  const [library, setLibrary] = useState<LibraryTrack[] | null>(null);

  useEffect(() => { setDraft(parseBrief(brief)); }, [brief]);
  // Compared by content: the parent hands a fresh array on every render.
  const tracksKey = JSON.stringify(tracks);
  useEffect(() => { setPicked(tracks); }, [tracksKey]);
  useEffect(() => {
    if (catalogCache) return;
    getJson<Catalog>('/api/music/styles')
      .then((c) => { catalogCache = c; setCatalog(c); })
      .catch(() => { /* the selects stay empty; free text still works */ });
  }, []);
  const loadLibrary = () => {
    getJson<{ tracks: LibraryTrack[] }>('/api/music/library')
      .then((r) => setLibrary(r.tracks || []))
      .catch(() => setLibrary([]));
  };
  useEffect(loadLibrary, []);

  const save = (next: Brief) => {
    setDraft(next);
    onPatch({ music_brief: serializeBrief(next) });
  };
  const savePicked = (next: PickedTrack[]) => {
    setPicked(next);
    onPatch({ music_tracks: next.length ? next : null });
  };
  // A slider drag updates the row live and is saved when it is let go.
  const setLevel = (file: string, volume_db: number) =>
    setPicked((cur) => cur.map((t) => (t.file === file ? { ...t, volume_db } : t)));

  const off = disabled || !music;
  const usingPicks = picked.length > 0;
  const autoOff = off || usingPicks;
  const engines = catalog?.engines ?? [{ name: 'ace_step', label: 'ACE-Step', max_seconds: 240 }, { name: 'stable_audio', label: 'Stable Audio Open', max_seconds: 47 }];
  const instruments = Object.values(catalog?.instruments ?? {}).flat();
  const hasBrief = Boolean(serializeBrief(draft));
  const labelOf = (file: string) => library?.find((t) => t.file === file)?.label ?? file.split('/').pop() ?? file;
  const addable = (library ?? []).filter((t) => t.license_ok && !picked.some((p) => p.file === t.file));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div className="vs-checks">
        <label className="vs-check" title="Off: the video gets no background music at all.">
          <input type="checkbox" checked={music} disabled={disabled}
            onChange={(e) => onPatch({ music: e.target.checked })} aria-label="Add background music" />
          Add background music
        </label>
        <label className="vs-check" title="Follow the [music: ...] cues the planner writes into the script -- the music changes at each one.">
          <input type="checkbox" checked={musicCues} disabled={autoOff}
            onChange={(e) => onPatch({ music_cues: e.target.checked })} aria-label="Follow music cues in the script" />
          Follow music cues in the script
        </label>
        <label className="vs-check" title="The model new tracks are generated with. Stable Audio Open makes loops up to 47 s, looped under longer sections.">
          Engine
          <select className="form-control" value={engine} disabled={autoOff}
            onChange={(e) => onPatch({ music_engine: e.target.value })} aria-label="Engine" style={{ width: 170, marginLeft: 6 }}>
            {engines.map((e) => <option key={e.name} value={e.name}>{e.label}</option>)}
          </select>
        </label>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center', opacity: autoOff ? 0.55 : 1 }}
        title="Music for the whole video. Leave empty to let the planner's cues and the channel's taste decide.">
        <select className="form-control" value={draft.style} disabled={autoOff} style={{ width: 170 }}
          onChange={(e) => save({ ...draft, style: e.target.value })} aria-label="Music style">
          <option value="">Preset: auto</option>
          {catalog?.styles.map((s) => <option key={s.name} value={s.name}>{s.label}</option>)}
        </select>
        <select className="form-control" value="" disabled={autoOff} style={{ width: 160 }}
          onChange={(e) => e.target.value && !draft.instruments.includes(e.target.value)
            && save({ ...draft, instruments: [...draft.instruments, e.target.value] })} aria-label="Add instrument">
          <option value="">+ Instrument</option>
          {instruments.map((i) => <option key={i} value={i}>{i}</option>)}
        </select>
        <select className="form-control" value={draft.mood} disabled={autoOff} style={{ width: 130 }}
          onChange={(e) => save({ ...draft, mood: e.target.value })} aria-label="Mood">
          <option value="">Mood: auto</option>
          {Object.keys(catalog?.moods ?? {}).map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <input className="form-control" type="number" min={50} max={180} placeholder="bpm" value={draft.bpm} disabled={autoOff}
          style={{ width: 80 }} onChange={(e) => setDraft({ ...draft, bpm: e.target.value })}
          onBlur={() => save(draft)} aria-label="BPM" />
        <input className="form-control" placeholder="Extra words, e.g. rain, monsoon" value={draft.text} disabled={autoOff}
          style={{ flex: 1, minWidth: 160 }} onChange={(e) => setDraft({ ...draft, text: e.target.value })}
          onBlur={() => save(draft)} aria-label="Extra words" />
        {hasBrief && (
          <button type="button" className="btn btn-outline btn-sm" disabled={autoOff}
            onClick={() => save({ style: '', instruments: [], mood: '', bpm: '', text: '' })}>Clear</button>
        )}
      </div>
      {draft.instruments.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {draft.instruments.map((i) => (
            <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: '0.78rem', padding: '2px 8px', borderRadius: 999, border: '1px solid var(--active-menu-border, #a78bfa)' }}>
              {i}
              <button type="button" disabled={autoOff} aria-label={`Remove ${i}`}
                onClick={() => save({ ...draft, instruments: draft.instruments.filter((x) => x !== i) })}
                style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: 'var(--text-muted)', display: 'inline-flex' }}>
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
      <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>
        {!music ? 'No music in this video.'
          : usingPicks ? 'Using your tracks below; the automatic music above is ignored.'
            : hasBrief ? `Whole-video music: ${serializeBrief(draft)}${musicCues ? ' — script cues change it from their point on.' : '.'}`
              : musicCues ? 'Auto: the planner writes [music: …] cues into the script, in the channel\'s music style.'
                : 'Auto: library beds chosen by each act\'s mood (missing moods are generated).'}
      </div>

      <div style={{ borderTop: '1px solid var(--border-subtle, rgba(255,255,255,0.08))', paddingTop: 8, display: 'flex', flexDirection: 'column', gap: 8, opacity: off ? 0.55 : 1 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
          <strong style={{ fontSize: '0.85rem' }}>Your tracks</strong>
          <select className="form-control" value="" disabled={off || !addable.length} style={{ width: 230 }}
            title="Pick tracks from the music library. Only tracks with a licence on record are listed."
            onChange={(e) => e.target.value && savePicked([...picked, { file: e.target.value, volume_db: DEFAULT_DB, duck: false }])}
            aria-label="Add track from library">
            <option value="">{library === null ? 'Loading library…' : addable.length ? '+ Add from library' : 'No more library tracks'}</option>
            {addable.map((t) => (
              <option key={t.file} value={t.file}>
                {t.label}{t.genre ? ` · ${t.genre}` : ''}{t.seconds ? ` · ${Math.round(t.seconds)}s` : ''}
              </option>
            ))}
          </select>
          {picked.length > 1 && (
            <select className="form-control" value={tracksMode === 'sequence' ? 'sequence' : 'together'} disabled={off}
              style={{ width: 210 }} onChange={(e) => onPatch({ music_tracks_mode: e.target.value })}
              aria-label="Track play order"
              title="Together: every track plays under the whole video, layered. One after another: each plays once, crossfading into the next, and the list repeats.">
              <option value="together">Play together (layered)</option>
              <option value="sequence">One after another (repeat)</option>
            </select>
          )}
          <MusicUpload compact disabled={off} onToast={onToast}
            onUploaded={(made) => {
              loadLibrary();
              savePicked([...picked, ...made.filter((m) => !picked.some((p) => p.file === m.file))
                .map((m) => ({ file: m.file, volume_db: DEFAULT_DB, duck: false }))]);
            }} />
        </div>
        {picked.map((t) => (
          <div key={t.file} style={{ display: 'flex', flexWrap: 'wrap', gap: 10, alignItems: 'center', padding: '6px 10px', border: '1px solid var(--border-subtle, rgba(255,255,255,0.08))', borderRadius: 8 }}>
            <div style={{ minWidth: 140, flex: 1, fontSize: '0.82rem' }} title={t.file}>
              {labelOf(t.file)}
              {library && library.length > 0 && !library.some((l) => l.file === t.file && l.license_ok) && (
                <span style={{ color: '#f87171', fontSize: '0.74rem' }}> · not in the library (or no licence): skipped</span>
              )}
            </div>
            <TrackPreview src={trackUrl(t.file)} db={t.volume_db} />
            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: '0.8rem' }}
              title="This track's fixed level in dB. Tracks are evened out to about the voice's loudness, so 0 dB is as loud as the voice and -20 dB sits well under it.">
              Volume
              <input type="range" min={DB_MIN} max={DB_MAX} step={1} value={Math.max(DB_MIN, t.volume_db)} disabled={off}
                onChange={(e) => setLevel(t.file, Number(e.target.value))}
                onPointerUp={() => savePicked(picked)} onKeyUp={() => savePicked(picked)}
                aria-label={`Volume for ${labelOf(t.file)}`}
                style={{ width: 130 }} />
              <input className="form-control" type="number" min={-60} max={DB_MAX} step={1} value={t.volume_db} disabled={off}
                onChange={(e) => setLevel(t.file, Math.max(-60, Math.min(DB_MAX, Number(e.target.value) || 0)))}
                onBlur={() => savePicked(picked)} aria-label={`Volume for ${labelOf(t.file)}`} style={{ width: 80 }} />
              dB
            </label>
            <label className="vs-check" title="Push this track down while you speak and back up in the pauses. Off: it stays at exactly the level you set.">
              <input type="checkbox" checked={t.duck} disabled={off}
                onChange={(e) => savePicked(picked.map((p) => (p.file === t.file ? { ...p, duck: e.target.checked } : p)))}
                aria-label={`Duck ${labelOf(t.file)} under voice`} />
              Duck under voice
            </label>
            <button type="button" disabled={off} aria-label={`Remove ${labelOf(t.file)}`} title="Remove from this video"
              onClick={() => savePicked(picked.filter((p) => p.file !== t.file))}
              style={{ background: 'none', border: 'none', padding: 2, cursor: 'pointer', color: 'var(--text-muted)', display: 'inline-flex' }}>
              <X size={14} />
            </button>
          </div>
        ))}
        {!picked.length && (
          <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>
            None picked, so the music is chosen automatically. Pick one or more tracks to use exactly those, at your own levels.
          </div>
        )}
      </div>
    </div>
  );
}
