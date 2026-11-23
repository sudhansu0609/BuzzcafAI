import { useEffect, useState } from 'react';
import { Instagram, RefreshCw, Trash2 } from 'lucide-react';
import { useStudio } from '../state/studio';
import { getJson, postJson, describeError } from '../services/api';
import type {
  InstagramAccountSettings, InstagramDiscoveredAccount, InstagramSettingsResponse, InstagramStatusResponse,
} from '../lib/types';

// Settings "Instagram Reels" card (REELS_DESK_PLAN.md R7): paste a Meta app id/
// secret and a long-lived token, discover the Facebook pages' Instagram
// accounts, save one as a named account, then route channels (and, where it
// matters, a specific format -- Life3Baje's mood reels post to a separate,
// calmer account, @khayal3bajefeels, from its ordinary reels) to it. The
// token itself is never shown back (GET masks it).

const timesToText = (t: string[]) => t.join(', ');
const textToTimes = (s: string) => s.split(',').map((t) => t.trim()).filter(Boolean);

interface AccountRow {
  enabled: boolean;
  postTimes: string;
  captionSuffix: string;
  saving: boolean;
}

export default function InstagramSettingsCard() {
  const { toast } = useStudio();
  const [channels, setChannels] = useState<string[]>([]);
  const [accounts, setAccounts] = useState<Record<string, InstagramAccountSettings>>({});
  const [routes, setRoutes] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<InstagramStatusResponse | null>(null);
  const [appId, setAppId] = useState('');
  const [appSecret, setAppSecret] = useState('');
  const [token, setToken] = useState('');
  const [discovering, setDiscovering] = useState(false);
  const [discovered, setDiscovered] = useState<InstagramDiscoveredAccount[]>([]);
  const [saveAsNames, setSaveAsNames] = useState<Record<string, string>>({});
  const [savingDiscovered, setSavingDiscovered] = useState<Record<string, boolean>>({});
  const [rows, setRows] = useState<Record<string, AccountRow>>({});
  const [newRouteKey, setNewRouteKey] = useState('');
  const [newRouteAccount, setNewRouteAccount] = useState('');
  const [savingRoutes, setSavingRoutes] = useState(false);

  const load = async () => {
    try {
      const [s, st] = await Promise.all([
        getJson<InstagramSettingsResponse>('/api/instagram/settings'),
        getJson<InstagramStatusResponse>('/api/instagram/status'),
      ]);
      setChannels(s.channels || []);
      setAccounts(s.accounts || {});
      setRoutes(s.routes || {});
      setStatus(st);
      setRows((prev) => {
        const next: Record<string, AccountRow> = {};
        for (const [name, acc] of Object.entries(s.accounts || {})) {
          next[name] = prev[name] || {
            enabled: !!acc.enabled, postTimes: timesToText(acc.post_times || []), captionSuffix: acc.caption_suffix || '',
            saving: false,
          };
        }
        return next;
      });
    } catch (err) {
      toast(`Could not load Instagram settings: ${describeError(err)}`, 'error');
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const discover = async () => {
    if (!token.trim()) {
      toast('Paste a long-lived token first.', 'info');
      return;
    }
    setDiscovering(true);
    try {
      const r = await postJson<{ accounts: InstagramDiscoveredAccount[] }>('/api/instagram/discover', { token: token.trim() });
      setDiscovered(r.accounts || []);
      setSaveAsNames(Object.fromEntries((r.accounts || []).map((a) => [a.ig_user_id, a.username || a.ig_user_id])));
      if (!r.accounts?.length) toast('No Instagram account found on that token\'s Facebook pages.', 'info');
      else toast(`Found ${r.accounts.length} Instagram account(s).`, 'success');
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setDiscovering(false);
    }
  };

  const saveDiscovered = async (a: InstagramDiscoveredAccount) => {
    const name = (saveAsNames[a.ig_user_id] || '').trim();
    if (!name) {
      toast('Give this account a name first.', 'info');
      return;
    }
    setSavingDiscovered((p) => ({ ...p, [a.ig_user_id]: true }));
    try {
      const payload: Record<string, unknown> = {
        account: name, ig_user_id: a.ig_user_id, username: a.username, access_token: a.access_token,
      };
      if (appId.trim()) payload.app_id = appId.trim();
      if (appSecret.trim()) payload.app_secret = appSecret.trim();
      await postJson('/api/instagram/settings', payload);
      toast(`Saved the account "${name}".`, 'success');
      await load();
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setSavingDiscovered((p) => ({ ...p, [a.ig_user_id]: false }));
    }
  };

  const setRow = (name: string, patch: Partial<AccountRow>) =>
    setRows((r) => ({ ...r, [name]: { ...r[name], ...patch } }));

  const saveAccount = async (name: string) => {
    const row = rows[name];
    if (!row) return;
    setRow(name, { saving: true });
    try {
      await postJson('/api/instagram/settings', {
        account: name, enabled: row.enabled, post_times: textToTimes(row.postTimes), caption_suffix: row.captionSuffix,
      });
      toast(`Instagram account "${name}" saved.`, 'success');
      await load();
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setRow(name, { saving: false });
    }
  };

  const saveRoute = async (key: string, account: string) => {
    if (!key.trim()) return;
    setSavingRoutes(true);
    try {
      const next = await postJson<{ routes: Record<string, string> }>('/api/instagram/routes', {
        routes: { [key.trim()]: account },
      });
      setRoutes(next.routes || {});
      toast(account ? `Routed ${key} -> ${account}.` : `Removed the route for ${key}.`, 'success');
      if (key === newRouteKey) { setNewRouteKey(''); setNewRouteAccount(''); }
      await load();
    } catch (err) {
      toast(describeError(err), 'error');
    } finally {
      setSavingRoutes(false);
    }
  };

  const accountNames = Object.keys(accounts);
  const routeSuggestions = channels.flatMap((ch) => [ch, ...['mood_reel'].map((f) => `${ch}/${f}`)]);

  return (
    <div className="panel-card">
      <h3 className="panel-title"><Instagram size={20} style={{ color: '#f472b6' }} /> Instagram Reels</h3>
      <p style={{ color: '#94a3b8', margin: '0 0 16px 0' }}>
        Posts a packaged reel (<code>publish/instagram/</code>: the video with its own audio, a cover and a caption)
        straight to Instagram as a Reel through the official Graph API. A channel can post to more than one account
        -- Life3Baje's mood reels default to a separate account, <code>@khayal3bajefeels</code>, from its ordinary
        reels -- which is why accounts are named and routed below rather than one slot per channel. See{' '}
        <code>docs/INSTAGRAM_SETUP.md</code> for where to get the app id/secret and the long-lived token.
      </p>

      <h4 style={{ margin: '0 0 8px', fontSize: '0.92rem', color: 'var(--text-primary)' }}>Connect an account</h4>
      <div className="form-row">
        <div className="form-group">
          <label>Meta app id</label>
          <input type="text" className="form-control" aria-label="Meta app id" value={appId}
            onChange={(e) => setAppId(e.target.value)} placeholder="123456789012345" />
        </div>
        <div className="form-group">
          <label>Meta app secret</label>
          <input type="password" className="form-control" aria-label="Meta app secret" value={appSecret}
            onChange={(e) => setAppSecret(e.target.value)} placeholder="Saved — type a new secret to replace it" />
        </div>
        <div className="form-group">
          <label>Long-lived token</label>
          <input type="password" className="form-control" aria-label="Instagram long-lived token" value={token}
            onChange={(e) => setToken(e.target.value)} placeholder="Paste a page/user token" />
        </div>
        <div className="form-group" style={{ flex: '0 0 auto', alignSelf: 'flex-end' }}>
          <button type="button" className="btn btn-outline" disabled={discovering} onClick={discover}>
            {discovering ? 'Discovering…' : 'Discover accounts'}
          </button>
        </div>
      </div>
      {discovered.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, margin: '0 0 16px' }}>
          {discovered.map((a) => (
            <div key={a.ig_user_id} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: '0.82rem' }}>
              <span>@{a.username || a.ig_user_id} ({a.page_name})</span>
              <input type="text" className="form-control" style={{ width: 180 }} aria-label={`Save @${a.username} as`}
                value={saveAsNames[a.ig_user_id] || ''} placeholder="account name (e.g. khayal3bajefeels)"
                onChange={(e) => setSaveAsNames((p) => ({ ...p, [a.ig_user_id]: e.target.value }))} />
              <button type="button" className="btn btn-outline" style={{ padding: '2px 10px' }}
                disabled={!!savingDiscovered[a.ig_user_id]} onClick={() => saveDiscovered(a)}>
                {savingDiscovered[a.ig_user_id] ? 'Saving…' : 'Save as account'}
              </button>
            </div>
          ))}
        </div>
      )}

      <h4 style={{ margin: '18px 0 8px', fontSize: '0.92rem', color: 'var(--text-primary)' }}>Accounts</h4>
      {accountNames.length === 0 ? (
        <p style={{ fontSize: '0.82rem', color: '#64748b', margin: '0 0 12px' }}>No account saved yet -- discover one above.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 16 }}>
          {accountNames.map((name) => {
            const row = rows[name];
            const st = status?.accounts?.[name];
            if (!row) return null;
            return (
              <div key={name} style={{ padding: '10px 12px', borderRadius: 8, border: '1px solid #334155' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <strong style={{ minWidth: 150 }}>{name}</strong>
                  <span style={{ fontSize: '0.78rem', color: st?.connected ? '#4ade80' : '#94a3b8' }}>
                    {st?.connected ? `✓ @${st.username || '?'}` : 'Not connected'}
                    {st?.token_expired ? ' · token expired' : st?.token_days_left != null && st.token_days_left < 10
                      ? ` · token expires in ${st.token_days_left}d` : ''}
                  </span>
                  {st?.publishing_limit && (
                    <span style={{ fontSize: '0.78rem', color: '#64748b' }}>
                      {st.publishing_limit.used}/{st.publishing_limit.total} posted today
                    </span>
                  )}
                </div>
                <div className="form-row" style={{ marginTop: 8 }}>
                  <div className="form-group" style={{ flex: '1 1 200px' }}>
                    <label>Post times (24h, comma separated)</label>
                    <input type="text" className="form-control" aria-label={`Post times for ${name}`} value={row.postTimes}
                      placeholder="19:30, 21:30" onChange={(e) => setRow(name, { postTimes: e.target.value })} />
                  </div>
                  <div className="form-group" style={{ flex: '1 1 200px' }}>
                    <label>Caption suffix (optional)</label>
                    <input type="text" className="form-control" aria-label={`Caption suffix for ${name}`} value={row.captionSuffix}
                      onChange={(e) => setRow(name, { captionSuffix: e.target.value })} />
                  </div>
                  <div className="form-group" style={{ flex: '0 0 auto', alignSelf: 'flex-end' }}>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', marginBottom: 8 }}>
                      <input type="checkbox" checked={row.enabled} onChange={(e) => setRow(name, { enabled: e.target.checked })} />
                      Auto-post nightly
                    </label>
                  </div>
                  <div className="form-group" style={{ flex: '0 0 auto', alignSelf: 'flex-end' }}>
                    <button type="button" className="btn btn-outline" disabled={row.saving} onClick={() => saveAccount(name)}>
                      {row.saving ? 'Saving…' : 'Save'}
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <h4 style={{ margin: '18px 0 8px', fontSize: '0.92rem', color: 'var(--text-primary)' }}>Routing</h4>
      <p style={{ fontSize: '0.8rem', color: '#64748b', margin: '0 0 10px' }}>
        Which account a channel posts to; a <code>channel/format</code> route (e.g. <code>Life3Baje/mood_reel</code>)
        wins over a plain channel route.
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 10 }}>
        {Object.entries(routes).map(([key, account]) => {
          const routeStatus = status?.routes?.[key];
          return (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: '0.84rem' }}>
              <code style={{ minWidth: 200 }}>{key}</code>
              <select className="form-control" style={{ width: 'auto' }} aria-label={`Account for ${key}`} value={account}
                onChange={(e) => saveRoute(key, e.target.value)}>
                <option value="">(unrouted)</option>
                {accountNames.map((n) => <option key={n} value={n}>{n}</option>)}
                {account && !accountNames.includes(account) && <option value={account}>{account} (not saved yet)</option>}
              </select>
              {routeStatus && !routeStatus.connected && (
                <span style={{ fontSize: '0.76rem', color: '#f59e0b' }}>unconnected until {account} has a token</span>
              )}
              <button type="button" className="btn btn-outline" style={{ padding: '2px 6px' }} title="Remove this route"
                disabled={savingRoutes} onClick={() => saveRoute(key, '')}>
                <Trash2 size={12} />
              </button>
            </div>
          );
        })}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <input type="text" className="form-control" style={{ width: 240 }} aria-label="New route (channel or channel/format)"
          value={newRouteKey} placeholder="Channel or Channel/format" list="instagram-route-suggestions"
          onChange={(e) => setNewRouteKey(e.target.value)} />
        <datalist id="instagram-route-suggestions">
          {routeSuggestions.map((s) => <option key={s} value={s} />)}
        </datalist>
        <select className="form-control" style={{ width: 'auto' }} aria-label="Account for the new route"
          value={newRouteAccount} onChange={(e) => setNewRouteAccount(e.target.value)}>
          <option value="">Pick an account</option>
          {accountNames.map((n) => <option key={n} value={n}>{n}</option>)}
        </select>
        <button type="button" className="btn btn-outline" disabled={savingRoutes || !newRouteKey.trim() || !newRouteAccount}
          onClick={() => saveRoute(newRouteKey, newRouteAccount)}>
          Add route
        </button>
      </div>

      <button type="button" className="btn btn-outline" style={{ marginTop: 14, padding: '2px 8px', fontSize: '0.74rem' }}
        onClick={load} title="Reload"><RefreshCw size={12} /></button>
    </div>
  );
}
