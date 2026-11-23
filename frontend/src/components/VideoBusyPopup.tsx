import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Clapperboard, X } from 'lucide-react';
import { setVideoBusyHandler, type VideoBusy, type VideoBusyChoice } from '../services/videoSlot';

// "Another video is being made" (2026-10-26): one video at a time, so the PC
// never lags. Shown whenever a start is refused because another video holds
// the slot (services/videoSlot.ts); the choice settles the original request.

export function VideoBusyPopup() {
  const [busy, setBusy] = useState<VideoBusy | null>(null);
  const resolver = useRef<((c: VideoBusyChoice) => void) | null>(null);

  useEffect(() => {
    setVideoBusyHandler((b) => new Promise<VideoBusyChoice>((resolve) => {
      // A second refusal while one is open: the newer one wins, the older is cancelled.
      resolver.current?.('cancel');
      resolver.current = resolve;
      setBusy(b);
    }));
    return () => setVideoBusyHandler(null);
  }, []);

  const choose = (c: VideoBusyChoice) => {
    resolver.current?.(c);
    resolver.current = null;
    setBusy(null);
  };

  useEffect(() => {
    if (!busy) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') choose('cancel'); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  if (!busy) return null;
  const a = busy.active || {};
  const doing = a.doing || a.what || 'being made';
  return createPortal(
    <div className="needs-you-overlay" role="dialog" aria-modal="true" aria-label="Another video is being made"
      onClick={() => choose('cancel')}>
      <div className="needs-you-card video-busy-card" onClick={(e) => e.stopPropagation()}>
        <div className="needs-you-head">
          <Clapperboard size={30} />
          <div style={{ flex: 1 }}>
            <div className="needs-you-title">Another video is being made</div>
            <div className="needs-you-sub">Only one video is made at a time, so the PC never lags or hangs.</div>
          </div>
          <button type="button" className="needs-you-close" onClick={() => choose('cancel')} aria-label="Cancel">
            <X size={22} />
          </button>
        </div>
        <div className="needs-you-list">
          <div className="needs-you-item" style={{ borderLeftColor: '#f97316' }}>
            <div className="needs-you-kind" style={{ color: '#f97316' }}>Running now</div>
            <div className="needs-you-name">{a.title || 'A video'}</div>
            <div className="needs-you-meta">{[a.brand, doing, a.progress_pct ? `${a.progress_pct}%` : ''].filter(Boolean).join(' · ')}</div>
            {a.progress_pct ? (
              <div className="video-busy-bar"><div style={{ width: `${Math.min(100, a.progress_pct)}%` }} /></div>
            ) : null}
            <div className="needs-you-what">
              {a.can_pause
                ? 'Start yours after it finishes, or pause it now and let yours go first.'
                : 'It is rendering and cannot be paused mid-render. Yours can start right after it.'}
            </div>
            <div className="needs-you-actions">
              <button type="button" className="needs-you-btn needs-you-btn-primary" onClick={() => choose('after')}>
                Start mine after it
              </button>
              {a.can_pause && a.queue_item_id && (
                <button type="button" className="needs-you-btn needs-you-btn-danger" onClick={() => choose('pause')}>
                  Pause it, start mine
                </button>
              )}
              <button type="button" className="needs-you-btn needs-you-btn-ghost" onClick={() => choose('cancel')}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
