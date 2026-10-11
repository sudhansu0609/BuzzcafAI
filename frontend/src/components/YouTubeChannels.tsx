import { useCallback, useEffect, useRef, useState } from 'react';
import { deleteJson, describeError, getJson, postJson } from '../services/api';

/** Bulk Editor tab -> YouTube channels: the creator's Google OAuth client, the
 *  channels signed in with it, and which Studio brand each one publishes
 *  (backend app/api/youtube_api.py). */

export type YtChannel = { id: string; title: string; brand?: string; thumbnail?: string; signed_in: boolean };
export type YtStatus = {
  has_client: boolean;
  channels: YtChannel[];
  brands: string[];
  login: { state: 'idle' | 'waiting' | 'done' | 'failed'; error?: string | null; channel?: string | null };
  categories: Record<string, string>;
};

export default function YouTubeChannels({ onChange }: { onChange?: (status: YtStatus) => void } = {}) {
  const [status, setStatus] = useState<YtStatus | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const poll = useRef<number | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => { if (status) onChange?.(status); }, [status, onChange]);

  const load = useCallback(async () => {
    try {
      const s = await getJson<YtStatus>('/api/youtube/status');
      setStatus(s);
      return s;
    } catch (err) {
      setError(describeError(err));
      return null;
    }
  }, []);

  useEffect(() => {
    load();
    return () => { if (poll.current) window.clearInterval(poll.current); };
  }, [load]);

  const watchLogin = () => {
    if (poll.current) window.clearInterval(poll.current);
    poll.current = window.setInterval(async () => {
      const s = await load();
      if (s && s.login.state !== 'waiting' && poll.current) {
        window.clearInterval(poll.current);
        poll.current = null;
        if (s.login.state === 'failed') setError(s.login.error || 'Sign-in failed.');
      }
    }, 2000);
  };

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError('');
    try {
      const res = await fn();
      if (res && typeof res === 'object' && 'channels' in res) setStatus(res as YtStatus);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  };

  const uploadClient = async (file: File) => {
    const text = await file.text();
    await act(() => postJson<YtStatus>('/api/youtube/client', { json: text }));
    if (fileInput.current) fileInput.current.value = '';
  };

  const connect = () => act(async () => {
    await postJson('/api/youtube/connect');
    watchLogin();
    return load();
  });

  const muted = { fontSize: '0.8rem', color: 'var(--text-secondary)' } as const;
  const waiting = status?.login.state === 'waiting';

  return (
    <div>
      <p style={{ ...muted, margin: '4px 0 12px' }}>
        Publish finished videos straight to your channels. Needs one Google Cloud OAuth client
        (type <b>Desktop app</b>, YouTube Data API v3 enabled); every channel then signs in once.
        Until Google audits that project, YouTube keeps API uploads <b>private</b>.
      </p>

      <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', marginBottom: 12 }}>
        <input ref={fileInput} type="file" accept=".json,application/json" style={{ display: 'none' }}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadClient(f); }} />
        <button type="button" className="btn btn-outline btn-sm" disabled={busy}
          onClick={() => fileInput.current?.click()}>
          {status?.has_client ? 'Replace Google client JSON' : 'Add Google client JSON'}
        </button>
        <span style={muted}>{status?.has_client ? 'Client added.' : 'No client yet.'}</span>
        <button type="button" className="btn btn-sm" disabled={busy || !status?.has_client || waiting} onClick={connect}>
          {waiting ? 'Waiting for Google sign-in…' : '+ Connect a channel'}
        </button>
      </div>
      {waiting && (
        <p style={{ ...muted, marginTop: 0 }}>
          Finish the sign-in in your browser. At the account chooser pick the <b>channel</b> (Brand Accounts are listed
          separately); on "Google hasn't verified this app" choose Advanced → Go to … → Continue.
        </p>
      )}
      {status?.login.state === 'done' && status.login.channel && (
        <p style={{ ...muted, color: '#22c55e', marginTop: 0 }}>Connected {status.login.channel}.</p>
      )}
      {error && <p style={{ fontSize: '0.8rem', color: '#f87171', marginTop: 0 }}>{error}</p>}

      {status && status.channels.length > 0 && (
        <table style={{ width: '100%', fontSize: '0.84rem', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ textAlign: 'left', color: 'var(--text-secondary)' }}>
              <th style={{ padding: '4px 6px' }}>Channel</th>
              <th style={{ padding: '4px 6px' }}>Publishes brand</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {status.channels.map((c) => (
              <tr key={c.id} style={{ borderTop: '1px solid var(--border-color, #333)' }}>
                <td style={{ padding: '8px 6px', verticalAlign: 'middle' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    {c.thumbnail && <img src={c.thumbnail} alt="" width={22} height={22} style={{ borderRadius: '50%' }} />}
                    <span>{c.title}</span>
                    {!c.signed_in && <span style={{ color: '#f87171' }}>(sign in again)</span>}
                  </div>
                </td>
                <td style={{ padding: '8px 6px', verticalAlign: 'middle' }}>
                  <select className="form-control" style={{ padding: '3px 6px', fontSize: '0.82rem' }} value={c.brand || ''}
                    disabled={busy}
                    onChange={(e) => act(() => postJson(`/api/youtube/channels/${c.id}/brand`, { brand: e.target.value }))}>
                    <option value="">— none —</option>
                    {status.brands.map((b) => <option key={b} value={b}>{b}</option>)}
                  </select>
                </td>
                <td style={{ padding: '8px 6px', textAlign: 'right', verticalAlign: 'middle' }}>
                  <button type="button" className="btn btn-outline btn-sm" disabled={busy}
                    onClick={() => { if (window.confirm(`Disconnect ${c.title}?`)) act(() => deleteJson(`/api/youtube/channels/${c.id}`)); }}>
                    Disconnect
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
