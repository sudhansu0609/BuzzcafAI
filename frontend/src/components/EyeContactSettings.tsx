import { useCallback, useEffect, useRef, useState } from 'react';
import { describeError, getJson, postJson, putJson } from '../services/api';

/** Teleprompter eye-contact correction for a project: BuzzEdit does the work
 *  (backend app/api/eye_contact_api.py drives it). "Fix during production"
 *  runs it right after the recording is imported; "Fix now" runs it on a
 *  project whose recording is already in BuzzEdit. Fields left alone use
 *  BuzzEdit's saved prompter setup. */

type Setup = {
  enabled?: boolean;
  prompter_side?: 'left' | 'right' | 'auto';
  angle_deg?: number;
  prompter_cm?: number;
  camera_cm?: number;
  steadiness?: number;
  aim_deg?: number;
  pitch_deg?: number;
  quality?: 'standard' | 'high' | 'max';
};
type Run = { state: 'running' | 'done' | 'failed'; stage?: string; progress?: number; error?: string | null };
type ProjectEye = { setup: Setup; applied: { at?: string; setup?: Setup } | null; run: Run | null };
type Defaults = { setup: Setup | null; available: boolean | null; reason?: string; buzzedit_running?: boolean; keep_alive?: boolean };

const FALLBACK: Required<Omit<Setup, 'enabled'>> = {
  prompter_side: 'left', angle_deg: 15, prompter_cm: 30, camera_cm: 110, steadiness: 0.7, aim_deg: -10, pitch_deg: 0, quality: 'high',
};

type Props = {
  projectId: string;
  hasRecording: boolean;
  disabled?: boolean;
  onToast?: (message: string, kind: 'success' | 'error' | 'info') => void;
};

export default function EyeContactSettings({ projectId, hasRecording, disabled, onToast }: Props) {
  const [data, setData] = useState<ProjectEye | null>(null);
  const [defaults, setDefaults] = useState<Defaults | null>(null);
  const [busy, setBusy] = useState(false);
  const [starting, setStarting] = useState(false);
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
  useEffect(() => {
    if (!running) {
      if (poll.current) window.clearInterval(poll.current);
      poll.current = null;
      return;
    }
    if (poll.current) return;
    poll.current = window.setInterval(async () => {
      const d = await load();
      if (d?.run && d.run.state !== 'running') {
        if (d.run.state === 'done') onToast?.('Eye contact fixed. Re-render to see it in the video.', 'success');
        else onToast?.(`Eye contact failed: ${d.run.error || 'unknown error'}`, 'error');
      }
    }, 2000);
  }, [running, load, onToast]);

  const setup = data?.setup ?? {};
  const base = { ...FALLBACK, ...(defaults?.setup ?? {}) };
  const value = <K extends keyof typeof FALLBACK>(k: K) => (setup[k] ?? base[k]) as (typeof FALLBACK)[K];

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

  const fixNow = async () => {
    setBusy(true);
    try {
      const run = await postJson<Run>(`${url}/run`, {});
      setData((prev) => (prev ? { ...prev, run } : prev));
    } catch (err) {
      onToast?.(describeError(err), 'error');
    } finally {
      setBusy(false);
    }
  };

  const revert = async () => {
    setBusy(true);
    try {
      await postJson(`${url}/revert`, {});
      onToast?.('Original recording restored in BuzzEdit.', 'info');
      void load();
    } catch (err) {
      onToast?.(describeError(err), 'error');
    } finally {
      setBusy(false);
    }
  };

  const enabled = Boolean(setup.enabled);
  const off = disabled || running;
  const num = (k: 'angle_deg' | 'prompter_cm' | 'camera_cm' | 'aim_deg' | 'pitch_deg', label: string, min: number, max: number,
    step: number, unit: string, hint: string) => (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: '0.74rem', color: 'var(--text-secondary)' }} title={hint}>
      <span>{label}: <b style={{ color: 'var(--text-primary)' }}>{value(k)}{unit}</b>
        {k === 'aim_deg' && Number(value(k)) !== 0 && (
          <span style={{ color: 'var(--text-muted)' }}> ({Number(value(k)) < 0 ? "← viewer's left" : "viewer's right →"})</span>
        )}
        {k === 'pitch_deg' && Number(value(k)) !== 0 && (
          <span style={{ color: 'var(--text-muted)' }}> ({Number(value(k)) > 0 ? '↓ lower' : '↑ higher'})</span>
        )}
      </span>
      <input type="range" min={min} max={max} step={step} value={Number(value(k))} disabled={off}
        onChange={(e) => setData((prev) => (prev ? { ...prev, setup: { ...prev.setup, [k]: Number(e.target.value) } } : prev))}
        onMouseUp={(e) => void patch({ [k]: Number((e.target as HTMLInputElement).value) })}
        onKeyUp={(e) => void patch({ [k]: Number((e.target as HTMLInputElement).value) })} />
    </label>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: '0.8rem' }}
        title="Re-aim your eyes at the lens when you read from a teleprompter. Runs in BuzzEdit on the GPU right after the recording is imported.">
        <input type="checkbox" checked={enabled} disabled={disabled} onChange={(e) => void patch({ enabled: e.target.checked })} />
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
          <input type="checkbox" checked={Boolean(defaults?.keep_alive)} onChange={(e) => void setKeepAlive(e.target.checked)} />
          <span>Keep BuzzEdit running in the background</span>
        </label>
      </div>
      {defaults?.buzzedit_running && defaults.available === false && (
        <span style={{ fontSize: '0.72rem', color: '#f59e0b' }}>Eye contact correction unavailable in BuzzEdit: {defaults.reason}</span>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10, opacity: enabled ? 1 : 0.75 }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: '0.74rem', color: 'var(--text-secondary)' }}
          title="Which side of the camera lens the prompter text is on, from where you sit. Auto works it out from your reading.">
          <span>Prompter side</span>
          <select className="form-control vs-select" value={value('prompter_side')} disabled={off}
            onChange={(e) => void patch({ prompter_side: e.target.value as Setup['prompter_side'] })}>
            <option value="left">Left of lens</option>
            <option value="right">Right of lens</option>
            <option value="auto">Auto-detect</option>
          </select>
        </label>
        {num('angle_deg', 'Prompter angle', 0, 45, 0.5, '°',
          'How far the prompter is from the lens, in degrees. 0 = work it out from the two distances below.')}
        {num('aim_deg', 'Aim nudge', -15, 15, 0.5, '°',
          "Where the pupils end up, as the audience sees it: − moves them toward the viewer's left, + toward the viewer's right. Default −10°.")}
        {num('pitch_deg', 'Up / down', -10, 10, 0.5, '°',
          'Moves the re-aimed pupils lower (+, looking down) or higher (−). Use it when the eyes read a little high or low after the fix. Default 0°.')}
        <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: '0.74rem', color: 'var(--text-secondary)' }}
          title="0 keeps the natural reading sweep; 1 locks the eyes on the lens.">
          <span>Steadiness: <b style={{ color: 'var(--text-primary)' }}>{Math.round(Number(value('steadiness')) * 100)}%</b></span>
          <input type="range" min={0} max={1} step={0.05} value={Number(value('steadiness'))} disabled={off}
            onChange={(e) => setData((prev) => (prev ? { ...prev, setup: { ...prev.setup, steadiness: Number(e.target.value) } } : prev))}
            onMouseUp={(e) => void patch({ steadiness: Number((e.target as HTMLInputElement).value) })}
            onKeyUp={(e) => void patch({ steadiness: Number((e.target as HTMLInputElement).value) })} />
        </label>
        {num('prompter_cm', 'Prompter offset', 0, 200, 1, ' cm', 'Sideways distance from the lens to the middle of the text (used when the angle is 0).')}
        {num('camera_cm', 'Camera distance', 20, 1000, 5, ' cm', 'Distance from your eyes to the camera (used when the angle is 0).')}
        <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: '0.74rem', color: 'var(--text-secondary)' }}
          title="Encoding quality of the corrected recording. Higher = bigger file, slower.">
          <span>Quality</span>
          <select className="form-control vs-select" value={value('quality')} disabled={off}
            onChange={(e) => void patch({ quality: e.target.value as Setup['quality'] })}>
            <option value="standard">Standard</option>
            <option value="high">High</option>
            <option value="max">Max</option>
          </select>
        </label>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <button type="button" className="btn btn-outline btn-sm" disabled={disabled || busy || running || !hasRecording}
          onClick={() => void fixNow()} style={{ padding: '3px 10px', fontSize: '0.74rem' }}
          title={hasRecording ? 'Correct the recording already in BuzzEdit with these settings' : 'Start video production first: the recording has to be in BuzzEdit'}>
          {running ? 'Fixing…' : 'Fix eye contact now'}
        </button>
        {data?.applied && (
          <button type="button" className="btn btn-outline btn-sm" disabled={disabled || busy || running}
            onClick={() => void revert()} style={{ padding: '3px 10px', fontSize: '0.74rem' }}
            title="Put the original recording back in BuzzEdit">
            Revert to original
          </button>
        )}
        <span style={{ fontSize: '0.72rem', color: data?.run?.state === 'failed' ? '#f87171' : 'var(--text-muted)' }}>
          {running
            ? `${data?.run?.stage || 'Working'} — ${Math.round((data?.run?.progress || 0) * 100)}%`
            : data?.run?.state === 'failed'
              ? `Failed: ${data.run.error}`
              : data?.applied
                ? `Applied ${data.applied.at ? data.applied.at.replace('T', ' ') : ''}. Re-render to use it.`
                : 'Not applied yet.'}
        </span>
      </div>
    </div>
  );
}
