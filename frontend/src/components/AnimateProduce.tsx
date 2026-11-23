import { useEffect, useState } from 'react';
import { getJson, postJson, describeError } from '../services/api';

type AnimationStatus = {
  state?: string;
  message?: string;
  error?: string | null;
  output_path?: string | null;
  has_screenplay?: boolean;
};

/** "Produce animation (BuzzAnimate)" for Khayal3Baje / Originals projects with a screenplay asset. */
export default function AnimateProduce({ projectId }: { projectId: string }) {
  const [st, setSt] = useState<AnimationStatus>({});
  const [err, setErr] = useState('');
  const base = `/api/projects/${encodeURIComponent(projectId)}/animation`;

  const load = async () => {
    try {
      setSt(await getJson<AnimationStatus>(base));
    } catch {
      /* status is best-effort */
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  const active = st.state === 'queued' || st.state === 'running';
  useEffect(() => {
    if (!active) return undefined;
    const t = window.setInterval(load, 5000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, projectId]);

  const start = async () => {
    setErr('');
    try {
      await postJson(`${base}/produce`, {});
      await load();
    } catch (e) {
      setErr(describeError(e));
    }
  };

  if (!st.has_screenplay) return null;
  return (
    <div style={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <button type="button" className="btn" disabled={active} onClick={start}>
          <span>{active ? 'Animating…' : 'Produce animation (BuzzAnimate)'}</span>
        </button>
        {st.state && st.state !== 'idle' && <span className="badge" style={{ fontSize: '0.75rem' }}>{st.state}</span>}
      </div>
      {active && st.message && <div style={{ fontSize: '0.8rem' }}>{st.message}</div>}
      {st.state === 'failed' && <div style={{ color: 'var(--danger, #c0392b)', fontSize: '0.8rem' }}>{st.error || st.message}</div>}
      {st.state === 'done' && st.output_path && <div style={{ fontSize: '0.8rem' }}>Episode: {st.output_path}</div>}
      {err && <div style={{ color: 'var(--danger, #c0392b)', fontSize: '0.8rem' }}>{err}</div>}
    </div>
  );
}
