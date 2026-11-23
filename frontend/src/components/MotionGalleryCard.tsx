import { useRef, useState } from 'react';
import { Clapperboard } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';

// Settings "Motion Gallery" card (docs/MOTION_GRAPHICS_PLAN.md M11): asks
// BuzzEdit to render every registered motion composition (kinetic text,
// maps, charts, transitions, stick scenes, the rest) with sample props,
// clean and noir, into a dated folder, then opens its index.html so every
// effect's look can be judged at a glance.

type GalleryState = {
  state: 'idle' | 'running' | 'completed' | 'failed' | string;
  folder?: string | null;
  count: number;
  total?: number;
  errors: Array<{ id: string; reason: string }>;
};

const POLL_MS = 2000;

export default function MotionGalleryCard() {
  const { toast } = useStudio();
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<GalleryState | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPoll = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const poll = () => {
    stopPoll();
    pollRef.current = setInterval(async () => {
      try {
        const data = await getJson<GalleryState>('/api/motion_gallery/status');
        setStatus(data);
        if (data.state === 'completed' || data.state === 'failed') {
          stopPoll();
          setBusy(false);
          if (data.state === 'completed') {
            setMessage(`Rendered ${data.count} effect${data.count === 1 ? '' : 's'}.`);
            try {
              await postJson('/api/motion_gallery/open');
            } catch (err) {
              toast(`Could not open the gallery folder: ${describeError(err)}`, 'error');
            }
          } else {
            setMessage('The motion gallery failed.');
            toast('The motion gallery failed to render.', 'error');
          }
        } else if (typeof data.total === 'number' && data.total > 0) {
          setMessage(`Rendering ${data.total} effect${data.total === 1 ? '' : 's'}... (${data.count} done)`);
        }
      } catch (err) {
        stopPoll();
        setBusy(false);
        toast(`Could not check the motion gallery: ${describeError(err)}`, 'error');
      }
    }, POLL_MS);
  };

  const start = async () => {
    setBusy(true);
    setStatus(null);
    setMessage('Starting…');
    try {
      const data = await postJson<GalleryState>('/api/motion_gallery/start', { themes: ['clean', 'noir'] });
      setStatus(data);
      const total = data.total || 0;
      setMessage(total > 0 ? `Rendering ${total} effect${total === 1 ? '' : 's'}...` : 'Rendering effects…');
      poll();
    } catch (err) {
      setBusy(false);
      setMessage(null);
      toast(`Could not start the motion gallery: ${describeError(err)}`, 'error');
    }
  };

  return (
    <div className="panel-card">
      <h3 className="panel-title"><Clapperboard size={20} /> Motion Gallery</h3>
      <p style={{ color: '#94a3b8', margin: '0 0 16px 0' }}>
        Renders every BuzzEdit motion template — kinetic text, maps, charts, transitions and the rest — with
        sample content, clean and noir, into a dated folder you can open and judge at a glance.
      </p>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <button type="button" className="btn btn-outline" disabled={busy} onClick={start}>
          {busy ? 'Rendering…' : 'Motion Gallery'}
        </button>
        {message && <span style={{ fontSize: '0.82rem', color: '#64748b' }}>{message}</span>}
      </div>
      {!busy && status?.errors && status.errors.length > 0 && (
        <p style={{ color: '#facc15', fontSize: '0.8rem', margin: '10px 0 0' }}>
          {status.errors.length} effect{status.errors.length === 1 ? '' : 's'} failed to render.
        </p>
      )}
    </div>
  );
}
