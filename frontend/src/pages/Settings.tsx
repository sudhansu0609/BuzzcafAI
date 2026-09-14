import { useEffect, useState, type FormEvent } from 'react';
import { CheckCircle2, Settings as SettingsIcon } from 'lucide-react';
import { useStudio } from '../state/studio';
import { postJson, describeError } from '../services/api';

const PROVIDERS = [
  { id: 'lm_studio', label: 'Local LM Studio' },
  { id: 'llamacpp', label: 'Local llama.cpp' },
  { id: 'gemini', label: 'Google Gemini' },
  { id: 'openai', label: 'OpenAI' },
];

// A tier may say "use whatever is selected above" by leaving the provider blank.
const TIER_PROVIDERS = [{ id: '', label: 'Same as the selected provider' }, ...PROVIDERS];

interface TierSetting {
  provider?: string;
  model?: string;
}

export default function Settings() {
  const { settings, refreshSettings, toast } = useStudio();
  const [provider, setProvider] = useState('lm_studio');
  const [geminiKey, setGeminiKey] = useState('');
  const [openaiKey, setOpenaiKey] = useState('');
  const [geminiModel, setGeminiModel] = useState('');
  const [openaiModel, setOpenaiModel] = useState('');
  const [lmStudioUrl, setLmStudioUrl] = useState('');
  const [lmStudioModel, setLmStudioModel] = useState('');
  const [llamacppUrl, setLlamacppUrl] = useState('');
  const [llamacppModel, setLlamacppModel] = useState('');
  const [tiers, setTiers] = useState<Record<string, TierSetting>>({ fast: {}, strong: {} });
  const [ownerChannels, setOwnerChannels] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!settings) return;
    const str = (key: string) => (typeof settings[key] === 'string' ? (settings[key] as string) : '');
    if (settings.selected_provider) setProvider(String(settings.selected_provider));
    setGeminiModel(str('gemini_model'));
    setOpenaiModel(str('openai_model'));
    setLmStudioUrl(str('lm_studio_url'));
    setLmStudioModel(str('lm_studio_model'));
    setLlamacppUrl(str('llamacpp_url'));
    setLlamacppModel(str('llamacpp_model'));
    const stored = settings.tiers as Record<string, TierSetting> | undefined;
    setTiers({ fast: stored?.fast || {}, strong: stored?.strong || {} });
    const owners = settings.owner_channel_ids;
    setOwnerChannels(Array.isArray(owners) ? owners.join(', ') : '');
  }, [settings]);

  const setTier = (name: string, patch: TierSetting) =>
    setTiers((prev) => ({ ...prev, [name]: { ...prev[name], ...patch } }));

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    const payload: Record<string, unknown> = {
      selected_provider: provider,
      prefer_gemini: provider === 'gemini',
      tiers: {
        fast: { provider: tiers.fast?.provider || '', model: tiers.fast?.model || '' },
        strong: { provider: tiers.strong?.provider || '', model: tiers.strong?.model || '' },
      },
      owner_channel_ids: ownerChannels.split(',').map((s) => s.trim()).filter(Boolean),
    };
    // Only send a key when one was typed: blank means "keep the stored key".
    if (geminiKey.trim()) payload.gemini_api_key = geminiKey.trim();
    if (openaiKey.trim()) payload.openai_api_key = openaiKey.trim();
    if (geminiModel.trim()) payload.gemini_model = geminiModel.trim();
    if (openaiModel.trim()) payload.openai_model = openaiModel.trim();
    if (lmStudioUrl.trim()) payload.lm_studio_url = lmStudioUrl.trim();
    if (lmStudioModel.trim()) payload.lm_studio_model = lmStudioModel.trim();
    if (llamacppUrl.trim()) payload.llamacpp_url = llamacppUrl.trim();
    if (llamacppModel.trim()) payload.llamacpp_model = llamacppModel.trim();
    try {
      await postJson('/api/settings', payload);
      setGeminiKey('');
      setOpenaiKey('');
      await refreshSettings();
      toast(`Settings saved. Active provider: ${provider}.`, 'success');
    } catch (err) {
      toast(`Could not save settings: ${describeError(err)}`, 'error');
    } finally {
      setSaving(false);
    }
  };

  const tierRow = (name: 'fast' | 'strong', description: string) => (
    <div className="form-row" style={{ alignItems: 'flex-end' }}>
      <div className="form-group">
        <label style={{ textTransform: 'capitalize' }}>{name} tier</label>
        <select
          className="form-control"
          value={tiers[name]?.provider || ''}
          onChange={(e) => setTier(name, { provider: e.target.value })}
        >
          {TIER_PROVIDERS.map((p) => <option key={p.id || 'inherit'} value={p.id}>{p.label}</option>)}
        </select>
      </div>
      <div className="form-group">
        <label>Model override (optional)</label>
        <input
          type="text"
          className="form-control"
          placeholder="leave blank to use that provider's model"
          value={tiers[name]?.model || ''}
          onChange={(e) => setTier(name, { model: e.target.value })}
        />
      </div>
      <div className="form-group" style={{ color: '#94a3b8', fontSize: '0.8rem', paddingBottom: 10 }}>{description}</div>
    </div>
  );

  return (
    <form onSubmit={save}>
      <div className="panel-card">
        <h3 className="panel-title"><SettingsIcon size={20} /> AI provider</h3>
        <p style={{ color: '#94a3b8', margin: '0 0 20px 0' }}>
          The Studio tries the selected provider first, then the others that are configured. Keys are stored server-side and never shown again.
        </p>
        <div className="form-group" style={{ marginBottom: 20 }}>
          <label>Selected provider</label>
          <select className="form-control" value={provider} onChange={(e) => setProvider(e.target.value)}>
            {PROVIDERS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </div>
        <div className="form-row">
          <div className="form-group">
            <label>LM Studio URL</label>
            <input type="text" className="form-control" placeholder="http://localhost:1234/v1" value={lmStudioUrl} onChange={(e) => setLmStudioUrl(e.target.value)} />
          </div>
          <div className="form-group">
            <label>LM Studio model</label>
            <input type="text" className="form-control" placeholder="meta-llama-3-8b-instruct" value={lmStudioModel} onChange={(e) => setLmStudioModel(e.target.value)} />
          </div>
        </div>
        <div className="form-row">
          <div className="form-group">
            <label>llama.cpp URL</label>
            <input type="text" className="form-control" placeholder="http://127.0.0.1:8089/v1" value={llamacppUrl} onChange={(e) => setLlamacppUrl(e.target.value)} />
          </div>
          <div className="form-group">
            <label>llama.cpp model</label>
            <input type="text" className="form-control" placeholder="local-model" value={llamacppModel} onChange={(e) => setLlamacppModel(e.target.value)} />
          </div>
        </div>
        <div className="form-row">
          <div className="form-group">
            <label>
              Google Gemini API key
              {settings?.gemini_api_key_set && <span style={{ marginLeft: 8, fontSize: '0.75rem', color: '#4ade80' }}>✓ key saved</span>}
            </label>
            <input type="password" className="form-control" placeholder={settings?.gemini_api_key_set ? 'Saved — type a new key to replace it' : 'AIzaSy…'} value={geminiKey} onChange={(e) => setGeminiKey(e.target.value)} />
          </div>
          <div className="form-group">
            <label>Gemini model</label>
            <input type="text" className="form-control" placeholder="gemini-1.5-flash" value={geminiModel} onChange={(e) => setGeminiModel(e.target.value)} />
          </div>
        </div>
        <div className="form-row">
          <div className="form-group">
            <label>
              OpenAI API key
              {settings?.openai_api_key_set && <span style={{ marginLeft: 8, fontSize: '0.75rem', color: '#4ade80' }}>✓ key saved</span>}
            </label>
            <input type="password" className="form-control" placeholder={settings?.openai_api_key_set ? 'Saved — type a new key to replace it' : 'sk-…'} value={openaiKey} onChange={(e) => setOpenaiKey(e.target.value)} />
          </div>
          <div className="form-group">
            <label>OpenAI model</label>
            <input type="text" className="form-control" placeholder="gpt-4o-mini" value={openaiModel} onChange={(e) => setOpenaiModel(e.target.value)} />
          </div>
        </div>
      </div>

      <div className="panel-card">
        <h3 className="panel-title"><SettingsIcon size={20} /> Model tiers</h3>
        <p style={{ color: '#94a3b8', margin: '0 0 20px 0' }}>
          Each persona declares a tier in its frontmatter. A tier's provider is tried first; if it is down, the normal fallback order still applies.
        </p>
        {tierRow('fast', 'Tags, titles, descriptions, checklists.')}
        {tierRow('strong', 'Research, scripts, strategy.')}
      </div>

      <div className="panel-card">
        <h3 className="panel-title"><SettingsIcon size={20} /> Your channels</h3>
        <div className="form-group" style={{ marginBottom: 20 }}>
          <label>Owned YouTube channel ids</label>
          <input
            type="text"
            className="form-control"
            placeholder="UCxxxx, UCyyyy"
            value={ownerChannels}
            onChange={(e) => setOwnerChannels(e.target.value)}
          />
          <span style={{ fontSize: '0.78rem', color: '#94a3b8', marginTop: 6 }}>
            Comma separated. BuzzBrain snapshots from these channels are marked as yours.
          </span>
        </div>
        <button type="submit" className="btn" disabled={saving}>
          <CheckCircle2 size={18} />
          <span>{saving ? 'Saving…' : 'Save settings'}</span>
        </button>
      </div>
    </form>
  );
}
