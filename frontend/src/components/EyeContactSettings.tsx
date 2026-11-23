import { useCallback, useEffect, useRef, useState } from 'react';
import type { CSSProperties, MouseEvent, MutableRefObject } from 'react';
import { describeError, getJson, postJson, putJson } from '../services/api';

/** Teleprompter eye-contact correction for a project: BuzzEdit does the work
 *  (backend app/api/eye_contact_api.py drives it). "Fix during production"
 *  runs it right after the recording is imported; "Fix now" runs it on a
 *  project whose recording is already in BuzzEdit.
 *
 *  Auto (the default) measures everything from the recording itself: the
 *  frames where you really look into the lens say where each iris sits then,
 *  sideways and up/down, and every reading frame is moved there. Manual is
 *  the old prompter geometry (side, angle, aim, up/down). "Preview" shows
 *  three before/after moments of the take before anything is rendered.
 *
 *  Since BuzzEdit's eye gaze v2 (2026-10-24) the lens is measured from head +
 *  eye gaze, or from the moments you mark (lens_marks); in Auto, angle / aim /
 *  up-down are nudges on top of that measurement (0 = measured). Nudges saved
 *  before v2 are ignored until one is saved again (the backend's nudges_v2). */

type Setup = {
  enabled?: boolean;
  mode?: 'auto' | 'manual';
  prompter_side?: 'left' | 'right' | 'auto';
  angle_deg?: number;
  prompter_cm?: number;
  camera_cm?: number;
  steadiness?: number;
  aim_deg?: number;
  pitch_deg?: number;
  quality?: 'standard' | 'high' | 'max';
  lens_marks?: number[];
  nudges_v2?: boolean;
};
type Live = { state: 'running' | 'done' | 'failed'; stage?: string; progress?: number; error?: string | null };
type Report = {
  auto_measured?: boolean; measured_shift_deg?: number; camera_look_pct?: number; corrected_pct?: number;
  prompter_offset_deg?: number; head_pitch_deg?: number; eyes_raised_deg?: number; median_shift_px?: number;
  eye_width_px?: number; duration_s?: number; face_found_pct?: number;
  lens_source?: 'marks' | 'measured' | 'geometry'; camera_look_candidates?: number[]; side_check?: string;
  median_shift_px_per_eye?: Record<string, number>; contact_sheet?: string;
};
type Clip = {
  start_s: number; duration_s: number; before_url: string; after_url: string; contact_sheet_url?: string | null;
  report?: Report;
};
type ProjectEye = {
  setup: Setup;
  applied: { at?: string; setup?: Setup; report?: Report } | null;
  run: Live | null;
  analysis?: { at?: string; setup?: Setup; report?: Report } | null;
  analysing?: Live | null;
  preview?: { at?: string; setup?: Setup; clips: Clip[] } | null;
  previewing?: Live | null;
};
type Defaults = { setup: Setup | null; available: boolean | null; reason?: string; buzzedit_running?: boolean; keep_alive?: boolean };

const FALLBACK: Required<Omit<Setup, 'enabled' | 'lens_marks' | 'nudges_v2'>> = {
  mode: 'auto', prompter_side: 'left', angle_deg: 0, prompter_cm: 30, camera_cm: 110, steadiness: 0.7, aim_deg: 0,
  pitch_deg: 0, quality: 'high',
};
const NUDGES = ['angle_deg', 'aim_deg', 'pitch_deg'] as const;

function perEye(px?: Record<string, number>) {
  if (!px || !Object.keys(px).length) return null;
  return Object.entries(px).map(([k, v]) => `${k} ${v} px`).join(', ');
}

type Props = {
  projectId: string;
  hasRecording: boolean;
  disabled?: boolean;
  onToast?: (message: string, kind: 'success' | 'error' | 'info') => void;
};

function fmtTime(s: number) {
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
}

/** One before/after pair, played in step: both videos start, seek and pause together. */
function PreviewPair({ clip, onLarge }: { clip: Clip; onLarge?: (clip: Clip) => void }) {
  const before = useRef<HTMLVideoElement | null>(null);
  const after = useRef<HTMLVideoElement | null>(null);
  const [playing, setPlaying] = useState(false);
  const [showAfter, setShowAfter] = useState(true);

  const both = (fn: (v: HTMLVideoElement) => void) => {
    [before.current, after.current].forEach((v) => v && fn(v));
  };
  const toggle = () => {
    if (playing) {
      both((v) => v.pause());
      setPlaying(false);
    } else {
      const t = before.current?.currentTime ?? 0;
      both((v) => {
        v.currentTime = t;
        void v.play().catch(() => undefined);
      });
      setPlaying(true);
    }
  };
  const restart = () => {
    both((v) => { v.currentTime = 0; });
  };
  const videoStyle = { width: '100%', borderRadius: 6, background: '#000', display: 'block' } as const;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
        <b style={{ color: 'var(--text-primary)' }}>At {fmtTime(clip.start_s)}</b>
        <button type="button" className="btn btn-outline btn-sm" style={{ padding: '1px 8px', fontSize: '0.7rem' }} onClick={toggle}>
          {playing ? 'Pause' : 'Play both'}
        </button>
        <button type="button" className="btn btn-outline btn-sm" style={{ padding: '1px 8px', fontSize: '0.7rem' }} onClick={restart}>
          Restart
        </button>
        {onLarge && (
          <button type="button" className="btn btn-primary btn-sm" style={{ padding: '1px 8px', fontSize: '0.7rem' }}
            onClick={() => onLarge(clip)} title="Open this moment full-screen; click on the eyes to zoom in.">
            Open large
          </button>
        )}
        <label style={{ display: 'flex', alignItems: 'center', gap: 4, marginLeft: 'auto', cursor: 'pointer' }}
          title="Flip between the original and the corrected clip in the same spot, which shows the change best.">
          <input type="checkbox" checked={!showAfter} onChange={(e) => setShowAfter(!e.target.checked)} />
          <span>Flip view</span>
        </label>
      </div>
      {showAfter ? (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
          <div>
            <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>Before</div>
            <video ref={before} src={clip.before_url} muted playsInline preload="metadata" style={videoStyle}
              onEnded={() => setPlaying(false)} />
          </div>
          <div>
            <div style={{ fontSize: '0.68rem', color: '#34d399' }}>After</div>
            <video ref={after} src={clip.after_url} muted playsInline preload="metadata" style={videoStyle} />
          </div>
        </div>
      ) : (
        <FlipView clip={clip} />
      )}
      {clip.report && (
        <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>
          {clip.report.corrected_pct != null && <>Re-aimed {clip.report.corrected_pct}% of frames</>}
          {clip.report.median_shift_px != null && <>, {clip.report.median_shift_px} px per iris</>}
          {perEye(clip.report.median_shift_px_per_eye) && <> (per eye: {perEye(clip.report.median_shift_px_per_eye)})</>}
          {clip.report.eyes_raised_deg != null && clip.report.eyes_raised_deg !== 0 && (
            <>, raised {clip.report.eyes_raised_deg}°</>
          )}
        </div>
      )}
      {clip.contact_sheet_url && (
        <div>
          <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>Eyes, before over after (click to open full size)</div>
          <a href={clip.contact_sheet_url} target="_blank" rel="noreferrer">
            <img src={clip.contact_sheet_url} alt={`Eye crops before over after at ${fmtTime(clip.start_s)}`}
              style={{ width: '100%', borderRadius: 6, display: 'block', background: '#000' }} />
          </a>
        </div>
      )}
    </div>
  );
}

/** The same spot of the frame, flipping between before and after every second. */
function FlipView({ clip }: { clip: Clip }) {
  const before = useRef<HTMLVideoElement | null>(null);
  const after = useRef<HTMLVideoElement | null>(null);
  const [after_on, setAfterOn] = useState(false);
  useEffect(() => {
    const id = window.setInterval(() => setAfterOn((v) => !v), 1000);
    const vids = [before.current, after.current];
    vids.forEach((v) => {
      if (v) { v.currentTime = 0; void v.play().catch(() => undefined); }
    });
    return () => window.clearInterval(id);
  }, []);
  const style = (visible: boolean) => ({
    width: '100%', borderRadius: 6, background: '#000', display: 'block', gridArea: '1 / 1',
    opacity: visible ? 1 : 0, transition: 'none',
  } as const);
  return (
    <div style={{ display: 'grid' }}>
      <video ref={before} src={clip.before_url} muted playsInline loop style={style(!after_on)} />
      <video ref={after} src={clip.after_url} muted playsInline loop style={style(after_on)} />
      <div style={{ gridArea: '1 / 1', alignSelf: 'start', justifySelf: 'end', margin: 6, padding: '1px 8px', borderRadius: 4,
        fontSize: '0.7rem', background: after_on ? '#065f46' : '#374151', color: '#fff' }}>
        {after_on ? 'After' : 'Before'}
      </div>
    </div>
  );
}

/** One moment full-screen: before and after side by side (or flipping), played in
 *  step, and a click anywhere on the picture zooms 3x on that spot -- the eyes are
 *  33 px wide in a medium shot, so this is where the change can be seen. */
function LargePreview({ clip, onClose }: { clip: Clip; onClose: () => void }) {
  const before = useRef<HTMLVideoElement | null>(null);
  const after = useRef<HTMLVideoElement | null>(null);
  const [flip, setFlip] = useState(false);
  const [afterOn, setAfterOn] = useState(false);
  const [zoom, setZoom] = useState<{ x: number; y: number; z: number } | null>(null);
  const [playing, setPlaying] = useState(true);
  const both = (fn: (v: HTMLVideoElement) => void) => [before.current, after.current].forEach((v) => v && fn(v));

  useEffect(() => {
    both((v) => { v.currentTime = 0; void v.play().catch(() => undefined); });
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clip.after_url]);
  useEffect(() => {
    if (!flip) return;
    const id = window.setInterval(() => setAfterOn((v) => !v), 1000);
    return () => window.clearInterval(id);
  }, [flip]);

  const toggle = () => {
    if (playing) both((v) => v.pause());
    else {
      const t = before.current?.currentTime ?? 0;
      both((v) => { v.currentTime = t; void v.play().catch(() => undefined); });
    }
    setPlaying(!playing);
  };
  const onPick = (e: MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width) * 100;
    const y = ((e.clientY - r.top) / r.height) * 100;
    setZoom((z) => (z && z.z >= 3 ? null : { x, y, z: z ? z.z + 1.5 : 3 }));
  };
  const vstyle = (visible: boolean): CSSProperties => ({
    width: '100%', display: 'block', background: '#000', gridArea: '1 / 1',
    opacity: visible ? 1 : 0,
    transform: zoom ? `scale(${zoom.z})` : undefined,
    transformOrigin: zoom ? `${zoom.x}% ${zoom.y}%` : undefined,
  });
  const panel = (label: string, color: string, ref: MutableRefObject<HTMLVideoElement | null>, src: string) => (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ color, fontSize: '0.85rem', marginBottom: 4, fontWeight: 600 }}>{label}</div>
      <div onClick={onPick} style={{ overflow: 'hidden', borderRadius: 8, cursor: zoom ? 'zoom-out' : 'zoom-in', display: 'grid' }}>
        <video ref={ref} src={src} muted playsInline loop style={vstyle(true)} />
      </div>
    </div>
  );
  return (
    <div role="dialog" aria-label="Eye contact preview" onClick={onClose}
      style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(0,0,0,0.92)', display: 'flex', flexDirection: 'column',
        padding: 16, gap: 10 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ display: 'flex', alignItems: 'center', gap: 10, color: '#e5e7eb', flexWrap: 'wrap' }}>
        <b>Eye contact preview at {fmtTime(clip.start_s)}</b>
        <button type="button" className="btn btn-outline btn-sm" onClick={toggle}>{playing ? 'Pause' : 'Play'}</button>
        <button type="button" className="btn btn-outline btn-sm" onClick={() => both((v) => { v.currentTime = 0; })}>Restart</button>
        <label style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer' }}>
          <input type="checkbox" checked={flip} onChange={(e) => setFlip(e.target.checked)} />
          <span>Flip before/after in one place</span>
        </label>
        <span style={{ color: '#9ca3af', fontSize: '0.8rem' }}>
          {zoom ? `Zoom ${zoom.z}x — click again to zoom more, or reset` : 'Click on the eyes to zoom in'}
        </span>
        {zoom && <button type="button" className="btn btn-outline btn-sm" onClick={() => setZoom(null)}>Reset zoom</button>}
        {clip.report?.median_shift_px != null && (
          <span style={{ color: '#9ca3af', fontSize: '0.8rem' }}>Iris moved {clip.report.median_shift_px} px{clip.report.eyes_raised_deg ? `, raised ${clip.report.eyes_raised_deg}°` : ''}</span>
        )}
        <button type="button" className="btn btn-outline btn-sm" style={{ marginLeft: 'auto' }} onClick={onClose}>Close (Esc)</button>
      </div>
      <div onClick={(e) => e.stopPropagation()} style={{ flex: 1, minHeight: 0, display: 'flex', gap: 12, alignItems: 'flex-start', justifyContent: 'center' }}>
        {flip ? (
          <div style={{ flex: 1, maxWidth: '70vw' }}>
            <div style={{ color: afterOn ? '#34d399' : '#e5e7eb', fontSize: '0.9rem', marginBottom: 4, fontWeight: 600 }}>{afterOn ? 'AFTER' : 'BEFORE'}</div>
            <div onClick={onPick} style={{ overflow: 'hidden', borderRadius: 8, cursor: zoom ? 'zoom-out' : 'zoom-in', display: 'grid' }}>
              <video ref={before} src={clip.before_url} muted playsInline loop style={vstyle(!afterOn)} />
              <video ref={after} src={clip.after_url} muted playsInline loop style={vstyle(afterOn)} />
            </div>
          </div>
        ) : (
          <>
            {panel('BEFORE', '#e5e7eb', before, clip.before_url)}
            {panel('AFTER (corrected)', '#34d399', after, clip.after_url)}
          </>
        )}
      </div>
    </div>
  );
}

export default function EyeContactSettings({ projectId, hasRecording, disabled, onToast }: Props) {
  const [data, setData] = useState<ProjectEye | null>(null);
  const [defaults, setDefaults] = useState<Defaults | null>(null);
  const [busy, setBusy] = useState(false);
  const [starting, setStarting] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [large, setLarge] = useState<Clip | null>(null);
  const poll = useRef<number | null>(null);
  const url = `/api/projects/${encodeURIComponent(projectId)}/eye_contact`;

  const load = useCallback(async () => {
    try {
      const d = await getJson<ProjectEye>(url);
      setData(d);
      return d;
    } catch {
      return null;
    }
  }, [url]);

  const loadDefaults = useCallback(() => {
    getJson<Defaults>('/api/eye_contact/defaults').then(setDefaults).catch(() => setDefaults(null));
  }, []);

  useEffect(() => {
    void load();
    loadDefaults();
    return () => {
      if (poll.current) window.clearInterval(poll.current);
    };
  }, [load, loadDefaults]);

  const startBuzzEdit = async () => {
    setStarting(true);
    try {
      await postJson('/api/produce/buzzedit/start', {});
      onToast?.('BuzzEdit is running in the background.', 'success');
    } catch (err) {
      onToast?.(`Could not start BuzzEdit: ${describeError(err)}`, 'error');
    } finally {
      setStarting(false);
      loadDefaults();
    }
  };

  const setKeepAlive = async (on: boolean) => {
    setDefaults((prev) => (prev ? { ...prev, keep_alive: on } : prev));
    try {
      await putJson('/api/produce/buzzedit/keep_alive', { enabled: on });
      if (on) onToast?.('BuzzEdit will be kept running in the background while the Studio is open.', 'info');
    } catch (err) {
      onToast?.(`Could not change the setting: ${describeError(err)}`, 'error');
    }
    window.setTimeout(loadDefaults, on ? 4000 : 500);
  };

  const running = data?.run?.state === 'running';
  const analysing = data?.analysing?.state === 'running';
  const previewing = data?.previewing?.state === 'running';
  const anyWork = running || analysing || previewing;
  useEffect(() => {
    if (!anyWork) {
      if (poll.current) window.clearInterval(poll.current);
      poll.current = null;
      return;
    }
    if (poll.current) return;
    poll.current = window.setInterval(async () => {
      const d = await load();
      if (!d) return;
      if (running && d.run && d.run.state !== 'running') {
        if (d.run.state === 'done') onToast?.('Eye contact fixed. Re-render to see it in the video.', 'success');
        else onToast?.(`Eye contact failed: ${d.run.error || 'unknown error'}`, 'error');
      }
      if (analysing && d.analysing && d.analysing.state !== 'running') {
        if (d.analysing.state === 'done') onToast?.('Measured. See the numbers below, or preview.', 'success');
        else onToast?.(`Measuring failed: ${d.analysing.error || 'unknown error'}`, 'error');
      }
      if (previewing && d.previewing && d.previewing.state !== 'running') {
        if (d.previewing.state === 'done') onToast?.('Preview ready.', 'success');
        else onToast?.(`Preview failed: ${d.previewing.error || 'unknown error'}`, 'error');
      }
    }, 2000);
  }, [anyWork, running, analysing, previewing, load, onToast]);

  const setup = data?.setup ?? {};
  const base = { ...FALLBACK, ...(defaults?.setup ?? {}) };
  const value = <K extends keyof typeof FALLBACK>(k: K) => (setup[k] ?? base[k]) as (typeof FALLBACK)[K];
  // In Auto, angle / aim / up-down are nudges on top of the measurement: 0 until one is
  // saved since eye gaze v2 (older values were ignored by Auto, and the backend drops them).
  const isNudge = (k: string) => value('mode') === 'auto' && (NUDGES as readonly string[]).includes(k);
  const shown = (k: 'angle_deg' | 'prompter_cm' | 'camera_cm' | 'aim_deg' | 'pitch_deg') =>
    isNudge(k) ? (setup.nudges_v2 ? Number(setup[k] ?? 0) : 0) : Number(value(k));

  const patch = async (p: Setup) => {
    setData((prev) => (prev ? { ...prev, setup: { ...prev.setup, ...p } } : prev));
    try {
      const r = await putJson<{ setup: Setup }>(url, p);
      setData((prev) => (prev ? { ...prev, setup: r.setup } : prev));
    } catch (err) {
      onToast?.(`Could not save eye contact settings: ${describeError(err)}`, 'error');
      void load();
    }
  };

  const call = async (what: 'run' | 'analyse' | 'preview' | 'revert', after?: string) => {
    setBusy(true);
    try {
      const live = await postJson<Live>(`${url}/${what}`, {});
      if (what === 'revert') {
        onToast?.('Original recording restored in BuzzEdit.', 'info');
        void load();
      } else {
        setData((prev) => (prev ? { ...prev, [what === 'run' ? 'run' : what === 'analyse' ? 'analysing' : 'previewing']: live } : prev));
        if (after) onToast?.(after, 'info');
      }
    } catch (err) {
      onToast?.(describeError(err), 'error');
    } finally {
      setBusy(false);
    }
  };

  const enabled = Boolean(setup.enabled);
  const mode = value('mode');
  const off = disabled || anyWork;
  const report = data?.analysis?.report;
  const applied = data?.applied?.report;
  const clips = data?.preview?.clips ?? [];
  // The lens as last measured: the whole-take analysis, else the latest preview's.
  const lensReport: Report | undefined = report ?? clips.find((c) => c.report?.lens_source)?.report;
  const lensPx = perEye(clips.find((c) => perEye(c.report?.median_shift_px_per_eye))?.report?.median_shift_px_per_eye)
    ?? (lensReport?.median_shift_px != null ? `${lensReport.median_shift_px} px per iris` : null);
  const candidates = lensReport?.camera_look_candidates ?? [];
  const marks = setup.lens_marks ?? [];
  const hasMark = (t: number) => marks.some((m) => Math.abs(m - t) < 0.3);
  const setMarks = (next: number[]) => patch({ lens_marks: [...next].sort((a, b) => a - b).map((t) => Math.round(t * 10) / 10) });

  const num = (k: 'angle_deg' | 'prompter_cm' | 'camera_cm' | 'aim_deg' | 'pitch_deg', label: string, min: number, max: number,
    step: number, unit: string, hint: string) => (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: '0.74rem', color: 'var(--text-secondary)' }} title={hint}>
      <span>{label}: <b style={{ color: 'var(--text-primary)' }}>{shown(k)}{unit}</b>
        {isNudge(k) && shown(k) === 0 && <span style={{ color: 'var(--text-muted)' }}> (measured)</span>}
        {k === 'aim_deg' && shown(k) !== 0 && (
          <span style={{ color: 'var(--text-muted)' }}> ({shown(k) < 0 ? "← viewer's left" : "viewer's right →"})</span>
        )}
        {k === 'pitch_deg' && shown(k) !== 0 && (
          <span style={{ color: 'var(--text-muted)' }}> ({shown(k) > 0 ? '↓ lower' : '↑ higher'})</span>
        )}
      </span>
      <input type="range" min={min} max={max} step={step} value={shown(k)} disabled={off}
        onChange={(e) => setData((prev) => (prev ? {
          ...prev, setup: { ...prev.setup, [k]: Number(e.target.value), ...(isNudge(k) ? { nudges_v2: true } : {}) },
        } : prev))}
        onMouseUp={(e) => void patch({ [k]: Number((e.target as HTMLInputElement).value) })}
        onKeyUp={(e) => void patch({ [k]: Number((e.target as HTMLInputElement).value) })} aria-label={label} />
    </label>
  );

  const measuredLine = (r: Report | undefined) => {
    if (!r) return null;
    if (r.auto_measured) {
      return (
        <>
          Measured from your own looks into the lens ({r.camera_look_pct ?? 0}% of the take): the eyes move{' '}
          <b style={{ color: 'var(--text-primary)' }}>{Math.abs(r.measured_shift_deg ?? 0)}°</b> sideways
          {r.eyes_raised_deg ? <> and <b style={{ color: 'var(--text-primary)' }}>{Math.abs(r.eyes_raised_deg)}°</b> {r.eyes_raised_deg > 0 ? 'up' : 'down'}</> : null}
          {r.median_shift_px != null ? <> (about {r.median_shift_px} px per iris at this framing)</> : null}.
        </>
      );
    }
    return (
      <>
        No look into the lens long enough to measure from ({r.camera_look_pct ?? 0}% of the take); using the
        symmetric guess: prompter {Math.abs(r.prompter_offset_deg ?? 0)}° off, head {r.head_pitch_deg ?? 0}° bowed.
        Look into the camera for a few seconds in your next take and Auto measures it.
      </>
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8rem' }}
        title="Re-aim your eyes at the lens when you read from a teleprompter. Runs in BuzzEdit on the GPU right after the recording is imported.">
        <input type="checkbox" checked={enabled} disabled={disabled} onChange={(e) => void patch({ enabled: e.target.checked })} aria-label="Fix eye contact during production" />
        <span>Fix eye contact during production</span>
      </label>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: '0.74rem' }}>
        <span style={{ color: defaults?.buzzedit_running ? '#34d399' : 'var(--text-muted)' }}>
          ● BuzzEdit {defaults?.buzzedit_running ? 'running' : starting ? 'starting…' : 'not running'}
        </span>
        {!defaults?.buzzedit_running && (
          <button type="button" className="btn btn-outline btn-sm" disabled={starting}
            onClick={() => void startBuzzEdit()} style={{ padding: '2px 8px', fontSize: '0.72rem' }}
            title="Start BuzzEdit headless (no window). Fixing eye contact and producing a video also start it when needed.">
            {starting ? 'Starting…' : 'Start BuzzEdit (background)'}
          </button>
        )}
        <label style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--text-secondary)' }}
          title="Start BuzzEdit when the Studio opens and restart it within a minute whenever it stops. The Studio still stops it when you close the Studio.">
          <input type="checkbox" checked={Boolean(defaults?.keep_alive)} onChange={(e) => void setKeepAlive(e.target.checked)} aria-label="Keep BuzzEdit running in the background" />
          <span>Keep BuzzEdit running in the background</span>
        </label>
      </div>
      {defaults?.buzzedit_running && defaults.available === false && (
        <span style={{ fontSize: '0.72rem', color: '#f59e0b' }}>Eye contact correction unavailable in BuzzEdit: {defaults.reason}</span>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', fontSize: '0.76rem' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer' }}
          title="Everything is measured from the recording: where your eyes sit when you really look into the lens becomes the target for every reading frame, sideways and up/down. Nothing to set.">
          <input type="radio" name={`eye-mode-${projectId}`} checked={mode === 'auto'} disabled={off} onChange={() => void patch({ mode: 'auto' })} />
          <span><b>Auto</b> — looks straight into the camera, measured from your take (recommended)</span>
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer' }}
          title="Set the prompter geometry yourself: side, angle, aim and up/down.">
          <input type="radio" name={`eye-mode-${projectId}`} checked={mode === 'manual'} disabled={off} onChange={() => void patch({ mode: 'manual' })} />
          <span>Manual</span>
        </label>
      </div>

      {mode === 'auto' && (
        <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', lineHeight: 1.45 }}>
          {report ? measuredLine(report) : (
            <>Auto needs a few seconds of you looking into the camera somewhere in the take (your intro does it). Press
            <b> Measure</b> to see what it found, or <b>Preview</b> to see before/after clips; production measures by itself.</>
          )}
        </div>
      )}
      {mode === 'auto' && lensReport?.lens_source && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
          <span style={{ padding: '1px 8px', borderRadius: 10, fontWeight: 600,
            background: lensReport.lens_source === 'geometry' ? '#78350f' : '#065f46', color: '#fff' }}
            title="Where the lens position came from: the moments you marked, your own held looks into the lens, or the prompter geometry when neither exists.">
            Lens: {lensReport.lens_source === 'marks' ? `from your ${marks.length} mark${marks.length === 1 ? '' : 's'}`
              : lensReport.lens_source === 'measured' ? 'measured from your looks' : 'geometry fallback'}
          </span>
          {lensReport.measured_shift_deg != null && <span><b style={{ color: 'var(--text-primary)' }}>{Math.abs(lensReport.measured_shift_deg)}°</b> sideways</span>}
          {lensPx && <span>eyes moved {lensPx}</span>}
        </div>
      )}
      {lensReport?.side_check && lensReport.side_check !== 'ok' && lensReport.side_check !== 'unclear' && (
        <span style={{ fontSize: '0.72rem', color: '#f59e0b' }}>
          Note: {lensReport.side_check}{mode === 'manual' ? ' — the prompter side is taken from your reading, not the setting.' : '.'}
        </span>
      )}
      {mode === 'auto' && (candidates.length > 0 || marks.length > 0) && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
          {candidates.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}
              title="Moments where you seem to hold a look into the lens. Mark the true ones and the lens is measured there.">
              <span>Looks into the lens at:</span>
              {candidates.map((t) => (
                <button key={t} type="button" className="btn btn-outline btn-sm" disabled={off || hasMark(t)}
                  style={{ padding: '1px 8px', fontSize: '0.7rem' }} onClick={() => void setMarks([...marks, t])}>
                  {fmtTime(t)} · {hasMark(t) ? 'marked' : 'Mark'}
                </button>
              ))}
            </div>
          )}
          {marks.length > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}
              title="The lens is measured from ±0.3 s around each mark. Measure or Preview again to use them.">
              <span>Your marks:</span>
              {marks.map((t) => (
                <button key={t} type="button" className="btn btn-outline btn-sm" disabled={off}
                  style={{ padding: '1px 8px', fontSize: '0.7rem' }} aria-label={`Remove mark ${fmtTime(t)}`}
                  onClick={() => void setMarks(marks.filter((m) => m !== t))}>
                  {fmtTime(t)} ×
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {(mode === 'manual' || showAdvanced) && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10, opacity: enabled ? 1 : 0.75 }}>
          <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: '0.74rem', color: 'var(--text-secondary)' }}
            title="Which side of the camera lens the prompter text is on, from where you sit. Auto works it out from your reading.">
            <span>Prompter side</span>
            <select className="form-control vs-select" value={value('prompter_side')} disabled={off}
              onChange={(e) => void patch({ prompter_side: e.target.value as Setup['prompter_side'] })} aria-label="Prompter side">
              <option value="left">Left of lens</option>
              <option value="right">Right of lens</option>
              <option value="auto">Symmetric guess</option>
            </select>
          </label>
          {mode === 'auto' && (
            <div style={{ gridColumn: '1 / -1', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
              Angle, aim and up/down are nudges on top of the measurement (0 = measured).
            </div>
          )}
          {num('angle_deg', mode === 'auto' ? 'Sideways angle override' : 'Prompter angle', 0, 45, 0.5, '°',
            mode === 'auto'
              ? 'Replaces the measured sideways swing with this many degrees (the direction stays measured). 0 = use the measurement.'
              : 'How far the prompter is from the lens, in degrees. 0 = work it out from the two distances below.')}
          {num('aim_deg', 'Aim nudge', -15, 15, 0.5, '°',
            mode === 'auto'
              ? "Added on top of the measured target, as the audience sees it: − toward the viewer's left, + toward the viewer's right. 0 = measured."
              : "Where the pupils end up, as the audience sees it: − moves them toward the viewer's left, + toward the viewer's right. Default 0°.")}
          {num('pitch_deg', 'Up / down', -10, 10, 0.5, '°',
            mode === 'auto'
              ? 'Added on top of the measured up/down: + lower (looking down), − higher. 0 = measured.'
              : 'Moves the re-aimed pupils lower (+, looking down) or higher (−). Use it when the eyes read a little high or low after the fix. Default 0°.')}
          <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: '0.74rem', color: 'var(--text-secondary)' }}
            title="Removes the slow line-by-line reading sweep; 0 keeps it. Natural eye movement (the quick small motions) always stays.">
            <span>Calm the reading sweep: <b style={{ color: 'var(--text-primary)' }}>{Math.round(Number(value('steadiness')) * 100)}%</b></span>
            <input type="range" min={0} max={1} step={0.05} value={Number(value('steadiness'))} disabled={off}
              onChange={(e) => setData((prev) => (prev ? { ...prev, setup: { ...prev.setup, steadiness: Number(e.target.value) } } : prev))}
              onMouseUp={(e) => void patch({ steadiness: Number((e.target as HTMLInputElement).value) })}
              onKeyUp={(e) => void patch({ steadiness: Number((e.target as HTMLInputElement).value) })} aria-label="Calm the reading sweep" />
          </label>
          {num('prompter_cm', 'Prompter offset', 0, 200, 1, ' cm', 'Sideways distance from the lens to the middle of the text (used when the angle is 0).')}
          {num('camera_cm', 'Camera distance', 20, 1000, 5, ' cm', 'Distance from your eyes to the camera (used when the angle is 0).')}
          <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: '0.74rem', color: 'var(--text-secondary)' }}
            title="Encoding quality of the corrected recording. Higher = bigger file, slower.">
            <span>Quality</span>
            <select className="form-control vs-select" value={value('quality')} disabled={off}
              onChange={(e) => void patch({ quality: e.target.value as Setup['quality'] })} aria-label="Quality">
              <option value="standard">Standard</option>
              <option value="high">High</option>
              <option value="max">Max</option>
            </select>
          </label>
        </div>
      )}
      {mode === 'auto' && (
        <button type="button" className="btn btn-link btn-sm" style={{ alignSelf: 'flex-start', padding: 0, fontSize: '0.7rem' }}
          onClick={() => setShowAdvanced((v) => !v)}>
          {showAdvanced ? 'Hide advanced' : 'Advanced (nudges, calm the sweep, quality, the manual fallback)'}
        </button>
      )}

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <button type="button" className="btn btn-outline btn-sm" disabled={off || busy || !hasRecording}
          onClick={() => void call('preview', 'Making three before/after clips…')} style={{ padding: '3px 10px', fontSize: '0.74rem' }}
          title={hasRecording ? 'Correct three short moments of the take and show them before/after. In Auto the take is measured first (once).' : 'Start video production first: the recording has to be in BuzzEdit'}>
          {previewing ? 'Previewing…' : 'Preview'}
        </button>
        {mode === 'auto' && (
          <button type="button" className="btn btn-outline btn-sm" disabled={off || busy || !hasRecording}
            onClick={() => void call('analyse', 'Measuring the whole take…')} style={{ padding: '3px 10px', fontSize: '0.74rem' }}
            title="Track the whole take once and show what Auto measured, without rendering anything.">
            {analysing ? 'Measuring…' : 'Measure'}
          </button>
        )}
        <button type="button" className="btn btn-outline btn-sm" disabled={off || busy || !hasRecording}
          onClick={() => void call('run')} style={{ padding: '3px 10px', fontSize: '0.74rem' }}
          title={hasRecording ? 'Correct the recording already in BuzzEdit with these settings' : 'Start video production first: the recording has to be in BuzzEdit'}>
          {running ? 'Fixing…' : 'Fix eye contact now'}
        </button>
        {data?.applied && (
          <button type="button" className="btn btn-outline btn-sm" disabled={off || busy}
            onClick={() => void call('revert')} style={{ padding: '3px 10px', fontSize: '0.74rem' }}
            title="Put the original recording back in BuzzEdit">
            Revert to original
          </button>
        )}
        {data?.applied && (
          <button type="button" className="btn btn-primary btn-sm" disabled={off || busy}
            style={{ padding: '3px 10px', fontSize: '0.74rem' }}
            title="Render the saved edit again with the corrected recording (pictures and clips are reused) and save the final video next to the recording."
            onClick={() => {
              setBusy(true);
              postJson(`/api/projects/${encodeURIComponent(projectId)}/produce_video/rerender`, {})
                .then(() => onToast?.('Queued: the video renders again with the corrected recording.', 'success'))
                .catch((err) => onToast?.(describeError(err), 'error'))
                .finally(() => setBusy(false));
            }}>
            Re-render video
          </button>
        )}
        <span style={{ fontSize: '0.72rem', color: data?.run?.state === 'failed' ? '#f87171' : 'var(--text-muted)' }}>
          {running
            ? `${data?.run?.stage || 'Working'} — ${Math.round((data?.run?.progress || 0) * 100)}%`
            : analysing
              ? `${data?.analysing?.stage || 'Measuring'} — ${Math.round((data?.analysing?.progress || 0) * 100)}%`
              : previewing
                ? `${data?.previewing?.stage || 'Previewing'} — ${Math.round((data?.previewing?.progress || 0) * 100)}%`
                : data?.run?.state === 'failed'
                  ? `Failed: ${data.run.error}`
                  : data?.applied
                    ? `Applied ${data.applied.at ? data.applied.at.replace('T', ' ') : ''}. Re-render to use it.`
                    : 'Not applied yet.'}
        </span>
      </div>
      {applied && data?.applied && (
        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Last run: {measuredLine(applied)}</div>
      )}

      {clips.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 4 }}>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
            Preview with the setup as it was at {data?.preview?.at ? data.preview.at.replace('T', ' ') : 'the last preview'}.
            Change anything above and press Preview again.
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 12 }}>
            {clips.map((clip) => <PreviewPair key={`${clip.start_s}-${clip.after_url}`} clip={clip} onLarge={setLarge} />)}
          </div>
        </div>
      )}
      {large && <LargePreview clip={large} onClose={() => setLarge(null)} />}
    </div>
  );
}
