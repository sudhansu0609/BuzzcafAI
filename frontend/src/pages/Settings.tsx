import { useEffect, useState, type FormEvent } from 'react';
import { CheckCircle2, Settings as SettingsIcon } from 'lucide-react';
import { useStudio } from '../state/studio';
import { postJson, describeError } from '../services/api';

const PROVIDERS = [
  { id: 'lm_studio', label: 'Local LM Studio (http://localhost:1234/v1)' },
  { id: 'gemini', label: 'Google Gemini (gemini-1.5-flash)' },
  { id: 'openai', label: 'OpenAI (gpt-4o-mini)' },
];

export default function Settings() {
  const { settings, refreshSettings, toast } = useStudio();
  const [provider, setProvider] = useState('lm_studio');
  const [geminiKey, setGeminiKey] = useState('');
  const [openaiKey, setOpenaiKey] = useState('');
  const [lmStudioUrl, setLmStudioUrl] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (settings?.selected_provider) setProvider(String(settings.selected_provider));
    if (typeof settings?.lm_studio_url === 'string') setLmStudioUrl(settings.lm_studio_url);
  }, [settings]);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    const payload: Record<string, unknown> = {
      selected_provider: provider,
      prefer_gemini: provider === 'gemini',
    };
    // Only send a key when one was typed: blank means "keep the stored key".
    if (geminiKey.trim()) payload.gemini_api_key = geminiKey.trim();
    if (openaiKey.trim()) payload.openai_api_key = openaiKey.trim();
    if (lmStudioUrl.trim()) payload.lm_studio_url = lmStudioUrl.trim();
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

  return (
    <div className="panel-card">
      <h3 className="panel-title"><SettingsIcon size={20} /> AI provider</h3>
      <p style={{ color: '#94a3b8', margin: '0 0 20px 0' }}>
        The Studio tries the selected provider first, then the others that are configured. Keys are stored server-side and never shown again.
      </p>
      <form onSubmit={save}>
        <div className="form-group" style={{ marginBottom: 20 }}>
          <label>Selected provider</label>
          <select className="form-control" value={provider} onChange={(e) => setProvider(e.target.value)}>
            {PROVIDERS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </div>
        <div className="form-group" style={{ marginBottom: 20 }}>
          <label>LM Studio URL</label>
          <input type="text" className="form-control" placeholder="http://localhost:1234/v1" value={lmStudioUrl} onChange={(e) => setLmStudioUrl(e.target.value)} />
        </div>
        <div className="form-group" style={{ marginBottom: 20 }}>
          <label>
            Google Gemini API key
            {settings?.gemini_api_key_set && <span style={{ marginLeft: 8, fontSize: '0.75rem', color: '#4ade80' }}>✓ key saved</span>}
          </label>
          <input type="password" className="form-control" placeholder={settings?.gemini_api_key_set ? 'Saved — type a new key to replace it' : 'AIzaSy…'} value={geminiKey} onChange={(e) => setGeminiKey(e.target.value)} />
        </div>
        <div className="form-group" style={{ marginBottom: 20 }}>
          <label>
            OpenAI API key
            {settings?.openai_api_key_set && <span style={{ marginLeft: 8, fontSize: '0.75rem', color: '#4ade80' }}>✓ key saved</span>}
          </label>
          <input type="password" className="form-control" placeholder={settings?.openai_api_key_set ? 'Saved — type a new key to replace it' : 'sk-…'} value={openaiKey} onChange={(e) => setOpenaiKey(e.target.value)} />
        </div>
        <button type="submit" className="btn" disabled={saving}>
          <CheckCircle2 size={18} />
          <span>{saving ? 'Saving…' : 'Save settings'}</span>
        </button>
      </form>
    </div>
  );
}
