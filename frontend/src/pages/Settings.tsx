import { useEffect, useState, type FormEvent } from 'react';
import { CheckCircle2, Settings as SettingsIcon, ShieldCheck, Globe, RefreshCw, Server, FastForward, Palette, RotateCcw } from 'lucide-react';
import { useStudio } from '../state/studio';
import { useTheme } from '../state/ThemeContext';
import { getThemeIcon } from '../components/ThemeSwitcher';
import { getJson, postJson, describeError } from '../services/api';

const PROVIDERS = [
  { id: 'lm_studio', label: 'Local LM Studio' },
  { id: 'ollama', label: 'Local Ollama' },
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

interface LocalModelsResponse {
  lm_studio: string[];
  ollama: string[];
  llamacpp: string[];
}

interface ModelPickerProps {
  label: string;
  value: string;
  onChange: (val: string) => void;
  models: string[];
  placeholder?: string;
  allowEmpty?: boolean;
  emptyLabel?: string;
}

function ModelPicker({
  label,
  value,
  onChange,
  models,
  placeholder = 'Select or enter model…',
  allowEmpty = false,
  emptyLabel = '-- Use default --',
}: ModelPickerProps) {
  const [isCustom, setIsCustom] = useState(false);
  const hasModels = Array.isArray(models) && models.length > 0;
  const isKnown = hasModels && models.includes(value);

  const showCustomInput = isCustom || (!isKnown && Boolean(value && !allowEmpty));

  return (
    <div className="form-group" style={{ flex: '1 1 260px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <label style={{ margin: 0 }}>{label}</label>
        {hasModels && (
          <button
            type="button"
            className="btn btn-outline"
            style={{ padding: '2px 8px', fontSize: '0.72rem', height: 'auto', border: '1px solid #334155' }}
            onClick={() => setIsCustom(!showCustomInput)}
          >
            {showCustomInput ? '← Pick from downloaded list' : '✎ Type custom name'}
          </button>
        )}
      </div>
      {showCustomInput || !hasModels ? (
        <input
          type="text"
          className="form-control"
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <select
          className="form-control"
          value={value}
          onChange={(e) => {
            if (e.target.value === '__custom__') {
              setIsCustom(true);
            } else {
              onChange(e.target.value);
            }
          }}
        >
          {allowEmpty && <option value="">{emptyLabel}</option>}
          {!allowEmpty && !value && <option value="">-- Choose from {models.length} downloaded models --</option>}
          {models.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
          {value && !models.includes(value) && (
            <option value={value}>Current: {value}</option>
          )}
          <option value="__custom__">✎ Enter custom model name…</option>
        </select>
      )}
    </div>
  );
}

export default function Settings() {
  const { settings, refreshSettings, toast, confirm } = useStudio();
  const { theme, themeDef: currentThemeDef, setTheme, themes } = useTheme();
  const [provider, setProvider] = useState('lm_studio');
  const [localOnly, setLocalOnly] = useState(true);
  const [geminiKey, setGeminiKey] = useState('');
  const [openaiKey, setOpenaiKey] = useState('');
  const [geminiModel, setGeminiModel] = useState('');
  const [openaiModel, setOpenaiModel] = useState('');
  const [lmStudioUrl, setLmStudioUrl] = useState('');
  const [lmStudioModel, setLmStudioModel] = useState('');
  const [ollamaUrl, setOllamaUrl] = useState('');
  const [ollamaModel, setOllamaModel] = useState('');
  const [llamacppUrl, setLlamacppUrl] = useState('');
  const [llamacppModel, setLlamacppModel] = useState('');
  const [tiers, setTiers] = useState<Record<string, TierSetting>>({ fast: {}, strong: {} });
  const [ownerChannels, setOwnerChannels] = useState('');
  const [allowAllSteps, setAllowAllSteps] = useState(false);
  const [webResearchEnabled, setWebResearchEnabled] = useState(true);
  const [searchProvider, setSearchProvider] = useState('auto');
  const [searxngUrl, setSearxngUrl] = useState('http://localhost:8080');
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [loadingModels, setLoadingModels] = useState(false);
  const [localModels, setLocalModels] = useState<LocalModelsResponse>({
    lm_studio: [],
    ollama: [],
    llamacpp: [],
  });
  const [testingSearxng, setTestingSearxng] = useState(false);
  const [searxngTestResult, setSearxngTestResult] = useState<{ status: string; message: string } | null>(null);

  const resetToDefaults = async () => {
    const ok = await confirm({
      title: 'Reset Settings to Factory Defaults?',
      body: 'This will restore all AI provider configurations, URLs, and tiers back to the factory defaults. Any customized API keys and model overrides will be reset.',
      danger: true,
      confirmLabel: 'Reset Settings',
    });
    if (!ok) return;

    setResetting(true);
    try {
      await postJson('/api/settings/reset', {});
      await refreshSettings();
      await fetchLocalModels();
      toast('Settings have been reset to factory defaults.', 'success');
    } catch (err) {
      toast(`Could not reset settings: ${describeError(err)}`, 'error');
    } finally {
      setResetting(false);
    }
  };

  const testSearxngConnection = async () => {
    setTestingSearxng(true);
    setSearxngTestResult(null);
    try {
      const res = await getJson<{ status: string; message: string }>(
        `/api/research/searxng-test?url=${encodeURIComponent(searxngUrl)}`
      );
      setSearxngTestResult(res);
    } catch (err: any) {
      setSearxngTestResult({
        status: 'error',
        message: `Failed to test SearXNG: ${err?.message || err}`,
      });
    } finally {
      setTestingSearxng(false);
    }
  };

  const fetchLocalModels = async () => {
    setLoadingModels(true);
    try {
      const data = await getJson<LocalModelsResponse>('/api/settings/local-models');
      if (data) {
        setLocalModels({
          lm_studio: Array.isArray(data.lm_studio) ? data.lm_studio : [],
          ollama: Array.isArray(data.ollama) ? data.ollama : [],
          llamacpp: Array.isArray(data.llamacpp) ? data.llamacpp : [],
        });
      }
    } catch (err) {
      console.warn('Could not fetch running local models', err);
    } finally {
      setLoadingModels(false);
    }
  };

  useEffect(() => {
    fetchLocalModels();
  }, []);

  useEffect(() => {
    if (!settings) return;
    const str = (key: string) => (typeof settings[key] === 'string' ? (settings[key] as string) : '');
    if (settings.selected_provider) setProvider(String(settings.selected_provider));
    if (settings.local_only !== undefined) setLocalOnly(Boolean(settings.local_only));
    if (settings.allow_all_steps !== undefined) setAllowAllSteps(Boolean(settings.allow_all_steps));
    setGeminiModel(str('gemini_model'));
    setOpenaiModel(str('openai_model'));
    setLmStudioUrl(str('lm_studio_url'));
    setLmStudioModel(str('lm_studio_model'));
    setOllamaUrl(str('ollama_url'));
    setOllamaModel(str('ollama_model'));
    setLlamacppUrl(str('llamacpp_url'));
    setLlamacppModel(str('llamacpp_model'));
    if (settings.web_research_enabled !== undefined) setWebResearchEnabled(Boolean(settings.web_research_enabled));
    if (settings.search_provider) setSearchProvider(String(settings.search_provider));
    if (settings.searxng_url) setSearxngUrl(String(settings.searxng_url));
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
      local_only: localOnly,
      prefer_gemini: provider === 'gemini',
      allow_all_steps: allowAllSteps,
      tiers: {
        fast: { provider: tiers.fast?.provider || '', model: tiers.fast?.model || '' },
        strong: { provider: tiers.strong?.provider || '', model: tiers.strong?.model || '' },
      },
      owner_channel_ids: ownerChannels.split(',').map((s) => s.trim()).filter(Boolean),
      web_research_enabled: webResearchEnabled,
      search_provider: searchProvider,
      searxng_url: searxngUrl.trim(),
    };
    // Only send a key when one was typed: blank means "keep the stored key".
    if (geminiKey.trim()) payload.gemini_api_key = geminiKey.trim();
    if (openaiKey.trim()) payload.openai_api_key = openaiKey.trim();
    if (geminiModel.trim()) payload.gemini_model = geminiModel.trim();
    if (openaiModel.trim()) payload.openai_model = openaiModel.trim();
    if (lmStudioUrl.trim()) payload.lm_studio_url = lmStudioUrl.trim();
    if (lmStudioModel.trim()) payload.lm_studio_model = lmStudioModel.trim();
    if (ollamaUrl.trim()) payload.ollama_url = ollamaUrl.trim();
    if (ollamaModel.trim()) payload.ollama_model = ollamaModel.trim();
    if (llamacppUrl.trim()) payload.llamacpp_url = llamacppUrl.trim();
    if (llamacppModel.trim()) payload.llamacpp_model = llamacppModel.trim();
    try {
      await postJson('/api/settings', payload);
      setGeminiKey('');
      setOpenaiKey('');
      await refreshSettings();
      await fetchLocalModels();
      toast(`Settings saved. Active provider: ${provider} (Strict Local: ${localOnly ? 'ON' : 'OFF'}).`, 'success');
    } catch (err) {
      toast(`Could not save settings: ${describeError(err)}`, 'error');
    } finally {
      setSaving(false);
    }
  };

  const tierRow = (name: 'fast' | 'strong', description: string) => {
    const rawTierProv = tiers[name]?.provider || '';
    const tierProv = rawTierProv || (provider !== 'gemini' && provider !== 'openai' ? provider : 'lm_studio');
    const detectedForTier =
      tierProv === 'lm_studio'
        ? localModels.lm_studio
        : tierProv === 'ollama'
        ? localModels.ollama
        : tierProv === 'llamacpp'
        ? localModels.llamacpp
        : tierProv === 'gemini'
        ? ['gemini-1.5-flash', 'gemini-1.5-pro']
        : tierProv === 'openai'
        ? ['gpt-4o-mini', 'gpt-4o']
        : [];

    return (
      <div className="form-row" style={{ alignItems: 'flex-end', marginBottom: 16 }}>
        <div className="form-group" style={{ flex: '1 1 200px' }}>
          <label style={{ textTransform: 'capitalize' }}>{name} tier</label>
          <select
            className="form-control"
            value={tiers[name]?.provider || ''}
            onChange={(e) => setTier(name, { provider: e.target.value })}
          >
            {TIER_PROVIDERS.map((p) => (
              <option key={p.id || 'inherit'} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
        <ModelPicker
          label={`Model override for ${name} tier`}
          value={tiers[name]?.model || ''}
          onChange={(m) => setTier(name, { model: m })}
          models={detectedForTier}
          allowEmpty={true}
          emptyLabel={`-- Use default (${tierProv} default) --`}
          placeholder="leave blank to use provider default"
        />
        <div className="form-group" style={{ color: '#94a3b8', fontSize: '0.8rem', paddingBottom: 10, flex: '1 1 180px' }}>
          {description}
        </div>
      </div>
    );
  };

  return (
    <form onSubmit={save}>
      {/* Appearance & Themes Section */}
      <div className="panel-card" style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 8 }}>
          <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0 }}>
            <Palette size={20} /> Appearance & Themes
          </h3>
          <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            Active: <strong style={{ color: 'var(--text-primary)' }}>{currentThemeDef.name}</strong>
          </span>
        </div>
        <p style={{ margin: '4px 0 16px', fontSize: '0.88rem', color: 'var(--text-secondary)' }}>
          Choose your visual style. Switch seamlessly between dark, light, semi-dark, minimalist, and vibrant funky themes.
        </p>

        <div className="theme-card-grid">
          {themes.map((t) => {
            const isActive = t.id === theme;
            return (
              <div
                key={t.id}
                className={`theme-preview-card ${isActive ? 'active' : ''}`}
                onClick={() => setTheme(t.id)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => e.key === 'Enter' && setTheme(t.id)}
              >
                <div className="theme-preview-banner" style={{ backgroundColor: t.colors.bg }}>
                  <div className="theme-banner-sidebar" style={{ backgroundColor: t.colors.sidebar, borderRight: `1px solid ${t.colors.border}` }}>
                    <div style={{ width: '60%', height: 4, borderRadius: 2, backgroundColor: t.colors.accent }} />
                    <div style={{ width: '80%', height: 3, borderRadius: 2, backgroundColor: t.colors.text, opacity: 0.3 }} />
                    <div style={{ width: '50%', height: 3, borderRadius: 2, backgroundColor: t.colors.text, opacity: 0.3 }} />
                  </div>
                  <div className="theme-banner-main">
                    <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                      <div style={{ flex: 1, height: 16, borderRadius: 4, backgroundColor: t.colors.card, border: `1px solid ${t.colors.border}` }} />
                      <div style={{ width: 24, height: 16, borderRadius: 4, background: `linear-gradient(135deg, ${t.colors.accent} 0%, ${t.colors.accentSecondary} 100%)` }} />
                    </div>
                    <div style={{ width: '70%', height: 4, borderRadius: 2, backgroundColor: t.colors.text, opacity: 0.7, marginTop: 4 }} />
                    <div style={{ width: '45%', height: 3, borderRadius: 2, backgroundColor: t.colors.text, opacity: 0.4 }} />
                  </div>
                </div>

                <div className="theme-card-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ color: t.colors.accent, display: 'flex' }}>
                      {getThemeIcon(t.iconName, 18)}
                    </span>
                    <h4 className="theme-card-title">{t.name}</h4>
                  </div>
                  <span className="theme-category-badge">{t.category}</span>
                </div>

                <p className="theme-card-desc">{t.description}</p>

                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginTop: 'auto', paddingTop: 8, borderTop: '1px solid var(--border-subtle)' }}>
                  <div className="theme-palette-dots">
                    <span className="theme-dot" style={{ backgroundColor: t.colors.bg, border: '1px solid var(--border-card)' }} />
                    <span className="theme-dot" style={{ backgroundColor: t.colors.card, border: '1px solid var(--border-card)' }} />
                    <span className="theme-dot" style={{ backgroundColor: t.colors.accent }} />
                    <span className="theme-dot" style={{ backgroundColor: t.colors.accentSecondary }} />
                  </div>
                  {isActive ? (
                    <span style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--border-highlight)', display: 'flex', alignItems: 'center', gap: 4 }}>
                      <CheckCircle2 size={14} /> Active
                    </span>
                  ) : (
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Click to activate</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Privacy Guarantee & Strict Local Mode Banner */}
      <div
        className="panel-card"
        style={{
          border: localOnly ? '1px solid #4ade80' : '1px solid #f59e0b',
          backgroundColor: localOnly ? 'rgba(74, 222, 128, 0.05)' : 'rgba(245, 158, 11, 0.05)',
          marginBottom: 20,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <ShieldCheck size={28} style={{ color: localOnly ? '#4ade80' : '#94a3b8' }} />
            <div>
              <h4 style={{ margin: 0, color: 'var(--text-primary)', fontSize: '1.05rem' }}>
                Strict Local Privacy Mode (Zero Data Leaves Your PC)
              </h4>
              <p style={{ margin: '4px 0 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                When enabled, all agent and subagent inference runs strictly on your local machine (LM Studio, Ollama, llama.cpp).
                Cloud AI APIs (Google Gemini, OpenAI) are completely disabled from fallback chains.
              </p>
            </div>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontWeight: 600 }}>
            <input
              type="checkbox"
              checked={localOnly}
              onChange={(e) => setLocalOnly(e.target.checked)}
              style={{ width: 18, height: 18, accentColor: '#4ade80' }}
            />
            <span>{localOnly ? 'Strict Local (Enforced)' : 'Allow Cloud Fallback'}</span>
          </label>
        </div>
      </div>

      <div className="panel-card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0 }}>
            <SettingsIcon size={20} /> AI Providers & Local Models
          </h3>
          <button
            type="button"
            className="btn btn-outline"
            style={{ padding: '4px 10px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: 6 }}
            onClick={fetchLocalModels}
            disabled={loadingModels}
          >
            <RefreshCw size={14} className={loadingModels ? 'spin' : ''} />
            <span>{loadingModels ? 'Scanning local ports…' : 'Re-scan local models'}</span>
          </button>
        </div>

        <p style={{ color: '#94a3b8', margin: '0 0 20px 0' }}>
          Choose your active local LLM engine. Models currently running on your system are detected automatically below.
        </p>

        <div className="form-group" style={{ marginBottom: 24 }}>
          <label>Selected Primary Provider</label>
          <select className="form-control" value={provider} onChange={(e) => setProvider(e.target.value)}>
            {PROVIDERS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </div>

        {/* 1. LM Studio Section with Model List */}
        <div style={{ borderTop: '1px solid #1e293b', paddingTop: 16, marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <strong style={{ color: '#e2e8f0', display: 'flex', alignItems: 'center', gap: 6 }}>
              <Server size={16} style={{ color: '#a78bfa' }} /> LM Studio
            </strong>
            {localModels.lm_studio.length > 0 ? (
              <span className="status-badge status-completed" style={{ fontSize: '0.75rem' }}>
                ✓ {localModels.lm_studio.length} models detected online
              </span>
            ) : (
              <span className="status-badge" style={{ fontSize: '0.75rem', opacity: 0.7 }}>
                Not detected on port 1234
              </span>
            )}
          </div>
          <div className="form-row">
            <div className="form-group" style={{ flex: '1 1 240px' }}>
              <label>LM Studio URL</label>
              <input
                type="text"
                className="form-control"
                placeholder="http://localhost:1234/v1"
                value={lmStudioUrl}
                onChange={(e) => setLmStudioUrl(e.target.value)}
              />
            </div>
            <ModelPicker
              label={`LM Studio Model (${localModels.lm_studio.length} downloaded)`}
              value={lmStudioModel}
              onChange={setLmStudioModel}
              models={localModels.lm_studio}
              placeholder="e.g. qwen3.8-flash-next"
            />
          </div>
        </div>

        {/* 2. Ollama Section with Model List */}
        <div style={{ borderTop: '1px solid #1e293b', paddingTop: 16, marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <strong style={{ color: '#e2e8f0', display: 'flex', alignItems: 'center', gap: 6 }}>
              <Server size={16} style={{ color: '#38bdf8' }} /> Ollama
            </strong>
            {localModels.ollama.length > 0 ? (
              <span className="status-badge status-completed" style={{ fontSize: '0.75rem' }}>
                ✓ {localModels.ollama.length} models detected online
              </span>
            ) : (
              <span className="status-badge" style={{ fontSize: '0.75rem', opacity: 0.7 }}>
                Not detected on port 11434
              </span>
            )}
          </div>
          <div className="form-row">
            <div className="form-group" style={{ flex: '1 1 240px' }}>
              <label>Ollama URL</label>
              <input
                type="text"
                className="form-control"
                placeholder="http://localhost:11434/v1"
                value={ollamaUrl}
                onChange={(e) => setOllamaUrl(e.target.value)}
              />
            </div>
            <ModelPicker
              label={`Ollama Model (${localModels.ollama.length} downloaded)`}
              value={ollamaModel}
              onChange={setOllamaModel}
              models={localModels.ollama}
              placeholder="e.g. qwen3.5:9b"
            />
          </div>
        </div>

        {/* 3. llama.cpp Section */}
        <div style={{ borderTop: '1px solid #1e293b', paddingTop: 16, marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <strong style={{ color: '#e2e8f0', display: 'flex', alignItems: 'center', gap: 6 }}>
              <Server size={16} style={{ color: '#f59e0b' }} /> llama.cpp / buzzcode Engine
            </strong>
            {localModels.llamacpp.length > 0 ? (
              <span className="status-badge status-completed" style={{ fontSize: '0.75rem' }}>
                ✓ {localModels.llamacpp.length} model detected online
              </span>
            ) : (
              <span className="status-badge" style={{ fontSize: '0.75rem', opacity: 0.7 }}>
                Not detected on port 8089
              </span>
            )}
          </div>
          <div className="form-row">
            <div className="form-group" style={{ flex: '1 1 240px' }}>
              <label>llama.cpp URL</label>
              <input
                type="text"
                className="form-control"
                placeholder="http://127.0.0.1:8089/v1"
                value={llamacppUrl}
                onChange={(e) => setLlamacppUrl(e.target.value)}
              />
            </div>
            <ModelPicker
              label={`llama.cpp Model (${localModels.llamacpp.length} available)`}
              value={llamacppModel}
              onChange={setLlamacppModel}
              models={localModels.llamacpp}
              placeholder="e.g. qwen3.8-27b"
            />
          </div>
        </div>

        {/* 4. Cloud Fallback Section (Visible only when localOnly is unchecked or configured) */}
        {!localOnly && (
          <div style={{ borderTop: '1px solid #1e293b', paddingTop: 16 }}>
            <p style={{ color: '#fca5a5', fontSize: '0.85rem', marginBottom: 12 }}>
              ⚠ Cloud providers enabled. Prompts will fall back to external servers if all local LLMs fail.
            </p>
            <div className="form-row">
              <div className="form-group">
                <label>
                  Google Gemini API key
                  {settings?.gemini_api_key_set && <span style={{ marginLeft: 8, fontSize: '0.75rem', color: '#4ade80' }}>✓ key saved</span>}
                </label>
                <input
                  type="password"
                  className="form-control"
                  placeholder={settings?.gemini_api_key_set ? 'Saved — type a new key to replace it' : 'AIzaSy…'}
                  value={geminiKey}
                  onChange={(e) => setGeminiKey(e.target.value)}
                />
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
                <input
                  type="password"
                  className="form-control"
                  placeholder={settings?.openai_api_key_set ? 'Saved — type a new key to replace it' : 'sk-…'}
                  value={openaiKey}
                  onChange={(e) => setOpenaiKey(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label>OpenAI model</label>
                <input type="text" className="form-control" placeholder="gpt-4o-mini" value={openaiModel} onChange={(e) => setOpenaiModel(e.target.value)} />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Model Tiers */}
      <div className="panel-card">
        <h3 className="panel-title"><SettingsIcon size={20} /> Model Tiers</h3>
        <p style={{ color: '#94a3b8', margin: '0 0 20px 0' }}>
          Each persona declares a tier in its frontmatter. Fast work (tags, titles, checklists) runs on the fast tier, while research, narration, and scripts run on the strong tier.
        </p>
        {tierRow('fast', 'Fast tasks: Tags, titles, checklists.')}
        {tierRow('strong', 'Heavy tasks: Research, scripts, direction.')}
      </div>

      {/* Web Research & SearXNG */}
      <div className="panel-card">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
          <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0 }}>
            <Globe size={20} style={{ color: '#38bdf8' }} /> Internet Access & Web Research (SearXNG / DDG / Wikipedia)
          </h3>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontWeight: 600 }}>
            <input
              type="checkbox"
              checked={webResearchEnabled}
              onChange={(e) => setWebResearchEnabled(e.target.checked)}
              style={{ width: 18, height: 18, accentColor: '#38bdf8' }}
            />
            <span>Enable Live Web Research</span>
          </label>
        </div>
        <p style={{ color: '#94a3b8', margin: '0 0 20px 0' }}>
          Allows research agents (WebResearcher, ResearchAgent, Studio Assistant) to search the web and fetch article text for accurate, cited scripts.
          Search queries are sanitized on-device: <strong>zero private project files or user credentials ever leave your PC</strong>.
        </p>

        <div className="form-row">
          <div className="form-group">
            <label>Search Provider</label>
            <select className="form-control" value={searchProvider} onChange={(e) => setSearchProvider(e.target.value)}>
              <option value="auto">Auto (SearXNG + DuckDuckGo + Wikipedia)</option>
              <option value="searxng">SearXNG (Self-Hosted Metasearch)</option>
              <option value="duckduckgo">DuckDuckGo (Anonymous Instant Answers)</option>
              <option value="wikipedia">Wikipedia (Encyclopedic Reference)</option>
            </select>
          </div>
          <div className="form-group">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
              <label style={{ margin: 0 }}>SearXNG URL (Default: http://localhost:8080)</label>
              <button
                type="button"
                className="btn btn-outline"
                style={{ padding: '2px 8px', fontSize: '0.75rem', height: 'auto' }}
                disabled={testingSearxng || !searxngUrl.trim()}
                onClick={testSearxngConnection}
              >
                {testingSearxng ? 'Testing…' : 'Test Connection'}
              </button>
            </div>
            <input
              type="text"
              className="form-control"
              placeholder="http://localhost:8080"
              value={searxngUrl}
              onChange={(e) => {
                setSearxngUrl(e.target.value);
                setSearxngTestResult(null);
              }}
            />
            {searxngTestResult && (
              <div
                style={{
                  marginTop: 6,
                  fontSize: '0.8rem',
                  padding: '4px 8px',
                  borderRadius: 4,
                  backgroundColor:
                    searxngTestResult.status === 'ok'
                      ? 'rgba(74, 222, 128, 0.1)'
                      : searxngTestResult.status === 'warning'
                      ? 'rgba(245, 158, 11, 0.1)'
                      : 'rgba(239, 68, 68, 0.1)',
                  color:
                    searxngTestResult.status === 'ok'
                      ? '#4ade80'
                      : searxngTestResult.status === 'warning'
                      ? '#f59e0b'
                      : '#fca5a5',
                  border: `1px solid ${
                    searxngTestResult.status === 'ok'
                      ? '#4ade80'
                      : searxngTestResult.status === 'warning'
                      ? '#f59e0b'
                      : '#ef4444'
                  }`,
                }}
              >
                {searxngTestResult.status === 'ok' ? '✓ ' : searxngTestResult.status === 'warning' ? '⚠ ' : '✕ '}
                {searxngTestResult.message}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Workflow Automation & Approvals */}
      <div className="panel-card">
        <h3 className="panel-title"><FastForward size={20} /> Workflow Automation & Approvals</h3>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h4 style={{ margin: 0, color: '#ffffff', fontSize: '1rem' }}>
              Allow All Workflow Steps (Skip Approval Pauses)
            </h4>
            <p style={{ margin: '4px 0 0', fontSize: '0.85rem', color: '#94a3b8' }}>
              When enabled globally, projects automatically advance through approval-gated steps without pausing to wait for manual approval.
            </p>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontWeight: 600 }}>
            <input
              type="checkbox"
              checked={allowAllSteps}
              onChange={(e) => setAllowAllSteps(e.target.checked)}
              style={{ width: 18, height: 18, accentColor: '#10b981' }}
            />
            <span style={{ color: allowAllSteps ? '#34d399' : '#e2e8f0' }}>
              {allowAllSteps ? 'Allow All (Continuous)' : 'Pause for Approval'}
            </span>
          </label>
        </div>
      </div>

      {/* Your Channels */}
      <div className="panel-card">
        <h3 className="panel-title"><SettingsIcon size={20} /> Your Channels</h3>
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
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
          <button type="submit" className="btn" disabled={saving || resetting} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            <CheckCircle2 size={18} />
            <span>{saving ? 'Saving…' : 'Save settings'}</span>
          </button>
          <button
            type="button"
            className="btn btn-outline"
            disabled={saving || resetting}
            onClick={resetToDefaults}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6, borderColor: '#ef4444', color: '#f87171' }}
          >
            <RotateCcw size={18} />
            <span>{resetting ? 'Resetting…' : 'Reset to defaults'}</span>
          </button>
        </div>
      </div>
    </form>
  );
}
