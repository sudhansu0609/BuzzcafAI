import { useEffect, useState } from 'react';
import { getJson } from '../services/api';

/** Estimated clips, stills and production time for the Video / Images mix,
 *  recomputed live as the sliders move. Inputs (running time, measured speeds)
 *  come from backend integrations/production_estimate.py, which mirrors this
 *  arithmetic in `estimate()`. */

type Inputs = {
  runtime: { seconds: number; source: string };
  speeds: { still_s: number; clip_s: number; render_factor: number; fixed_s: number; source: string };
  clip_seconds: number;
  still_seconds: number;
};

const cache = new Map<string, Inputs>();

function duration(seconds: number): string {
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  return `${h} h ${String(m % 60).padStart(2, '0')} min`;
}

export default function ProductionEstimate({ projectId, video, images }: { projectId: string; video: number; images: number }) {
  const [inputs, setInputs] = useState<Inputs | null>(cache.get(projectId) || null);

  useEffect(() => {
    let live = true;
    getJson<Inputs>(`/api/projects/${projectId}/produce_video/estimate`)
      .then((r) => { cache.set(projectId, r); if (live) setInputs(r); })
      .catch(() => undefined);
    return () => { live = false; };
  }, [projectId]);

  if (!inputs) return null;
  const runtime = inputs.runtime.seconds;
  const muted = { color: 'var(--text-secondary)' } as const;
  if (!runtime) {
    return (
      <div style={{ flexBasis: '100%', fontSize: '0.74rem', ...muted }}>
        Estimate: write the script or upload the recording to see how many clips this needs.
      </div>
    );
  }
  const { speeds } = inputs;
  const clips = Math.round((runtime * video) / inputs.clip_seconds);
  const stills = Math.round((runtime * images) / inputs.still_seconds);
  const picturesS = (clips + stills) * speeds.still_s;   // every clip starts from a still
  const clipsS = clips * speeds.clip_s;
  const renderS = runtime * speeds.render_factor;
  const totalS = picturesS + clipsS + renderS + speeds.fixed_s;
  const long = totalS > 3 * 3600;

  return (
    <div style={{ flexBasis: '100%', fontSize: '0.76rem', display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'baseline',
      padding: '6px 8px', borderRadius: 6, background: 'var(--bg-input, rgba(255,255,255,0.03))' }}>
      <b>Estimate</b>
      <span><b style={{ color: '#a78bfa' }}>{clips}</b> clips <span style={muted}>({duration(runtime * video)} of video)</span></span>
      <span><b style={{ color: '#38bdf8' }}>{stills}</b> stills</span>
      <span style={muted}>pictures {duration(picturesS)} · clips {duration(clipsS)} · render {duration(renderS)} · other {duration(speeds.fixed_s)}</span>
      <span>Total <b style={{ color: long ? '#f59e0b' : 'var(--text-primary)' }}>≈ {duration(totalS)}</b></span>
      <span style={{ ...muted, fontSize: '0.7rem' }}>
        for a {duration(runtime)} video ({inputs.runtime.source}); speeds from {speeds.source}, ~{Math.round(speeds.clip_s / 60 * 10) / 10} min per clip
      </span>
    </div>
  );
}
