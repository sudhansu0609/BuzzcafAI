import { AlertCircle, CheckCircle2, Info, X } from 'lucide-react';
import type { ToastItem } from '../lib/types';

// Every notification the Studio shows goes through here. The old UI used ten
// alert()/confirm() calls, which block the whole window and look nothing like
// the app; toasts and an in-app confirm dialog replace them (roadmap v5, 2.5).

const COLORS: Record<ToastItem['kind'], { fg: string; bg: string; border: string }> = {
  success: { fg: '#4ade80', bg: '#0b261d', border: '#4ade80' },
  error: { fg: '#fca5a5', bg: '#2d141b', border: '#7f1d1d' },
  info: { fg: '#38bdf8', bg: '#0c2233', border: '#1e5f8a' },
};

export function ToastHost({ toasts, onDismiss }: { toasts: ToastItem[]; onDismiss: (id: string) => void }) {
  if (toasts.length === 0) return null;
  return (
    <div className="toast-host-container">
      {toasts.map((t) => {
        const c = COLORS[t.kind];
        const Icon = t.kind === 'success' ? CheckCircle2 : t.kind === 'error' ? AlertCircle : Info;
        return (
          <div
            key={t.id}
            role="status"
            style={{
              background: c.bg,
              border: `1px solid ${c.border}`,
              color: c.fg,
              padding: '12px 16px',
              borderRadius: 8,
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              fontWeight: 600,
              maxWidth: '100%',
              boxShadow: '0 10px 25px rgba(0,0,0,0.5)',
              animation: 'slideIn 0.3s ease-out',
            }}
          >
            <Icon size={18} />
            <span style={{ flex: 1, fontSize: '0.9rem' }}>{t.text}</span>
            <button
              type="button"
              onClick={() => onDismiss(t.id)}
              aria-label="Dismiss"
              style={{ background: 'none', border: 'none', color: c.fg, cursor: 'pointer', display: 'flex' }}
            >
              <X size={14} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

export interface ConfirmRequest {
  title: string;
  body?: string;
  confirmLabel?: string;
  danger?: boolean;
}

export function ConfirmDialog({
  request,
  onAnswer,
}: {
  request: ConfirmRequest | null;
  onAnswer: (yes: boolean) => void;
}) {
  if (!request) return null;
  return (
    <div className="modal-overlay" onClick={() => onAnswer(false)} role="dialog" aria-modal="true">
      <div
        className="panel-card"
        style={{ width: 460, maxWidth: '90vw', margin: 0 }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3 style={{ margin: '0 0 10px 0', color: 'var(--text-primary)', fontSize: '1.1rem' }}>{request.title}</h3>
        {request.body && <p style={{ color: 'var(--text-secondary)', margin: '0 0 20px 0', lineHeight: 1.5 }}>{request.body}</p>}
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button type="button" className="btn btn-outline" onClick={() => onAnswer(false)}>
            <span>Cancel</span>
          </button>
          <button
            type="button"
            className="btn"
            style={request.danger ? { backgroundColor: '#7f1d1d', borderColor: '#7f1d1d' } : undefined}
            onClick={() => onAnswer(true)}
            autoFocus
          >
            <span>{request.confirmLabel || 'Confirm'}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
