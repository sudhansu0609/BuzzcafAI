import { useEffect, useState, type FormEvent } from 'react';
import { CheckCircle2, Settings as SettingsIcon, ShieldCheck, Globe, RefreshCw, Server, FastForward, Palette, RotateCcw, Sparkles, Film, Brain, Cpu, Pencil, Trash2, Copy } from 'lucide-react';
import { useStudio } from '../state/studio';
import { useTheme } from '../state/ThemeContext';
import { getThemeIcon } from '../components/ThemeSwitcher';
import ThemeBuilder from '../components/ThemeBuilder';
import ModelRoutingWindow from '../components/ModelRoutingWindow';
import type { ThemeDefinition } from '../lib/theme';
import { getJson, postJson, putJson, describeError } from '../services/api';
import { GENRES, DENSITIES, VOICE_PRESETS } from '../lib/types';
import type { ChannelProfile, ChannelProfilesResponse } from '../lib/types';
import { ART_STYLES } from '../lib/artStyles';
import SoundEffectsCard from '../components/SoundEffectsCard';
import MotionGalleryCard from '../components/MotionGalleryCard';
import InstagramSettingsCard from '../components/InstagramSettingsCard';

const PROVIDERS = [
  { id: 'lm_studio', label: 'Local LM Studio' },
  { id: 'gemini', label: 'Google Gemini (Local Harness @ 8001 / Cloud)' },
  { id: 'claude', label: 'Claude (local proxy)' },
  { id: 'ollama', label: 'Local Ollama' },
  { id: 'llamacpp', label: 'Local llama.cpp' },
  { id: 'openai', label: 'OpenAI' },
];

const GEMINI_MODELS = ['flash', 'argon', 'flash-lite', 'pro', 'gemini-2.5-flash', 'gemini-1.5-flash', 'gemini-1.5-pro'];

// GET /api/gemini/status
interface GeminiStatus {
  url: string;
  model: string;
  key_set: boolean;
  online: boolean;
  is_local: boolean;
  auth_mode: string;
  models: string[];
  message: string;
}

// Model names the claude-local-api proxy routes to Claude Code (its README,
// "Models and effort"). Anything else it forwards to its Codex fallback.
const CLAUDE_MODELS = ['sonnet', 'haiku', 'opus', 'claude-sonnet-5', 'claude-haiku-4-5', 'claude-opus-5', 'default'];

// GET /api/produce/claude/status
interface ClaudeStatus {
  url: string;
  model: string;
  key_set: boolean;
  online: boolean;
  authorized: boolean;
  models: string[];
  message: string;
  routed: boolean;
}

// GET /api/produce/stock/status
interface StockStatus {
  pixabay_enabled: boolean;
  pixabay_key_set: boolean;
  buzzedit: { pixabay_api_key_set?: boolean; pixabay_api_key?: string; pexels_api_key_set?: boolean } | null;
}

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
          aria-label={label}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <select
          className="form-control"
          aria-label={label}
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
  const { theme, themeDef: currentThemeDef, setTheme, themes, deleteCustomTheme } = useTheme();
  // The Theme Builder starts from this theme; the key remounts it on every "Customise".
  const [builderSeed, setBuilderSeed] = useState<{ def: ThemeDefinition; key: number } | null>(null);
  const openBuilder = (def: ThemeDefinition) => {
    setBuilderSeed((prev) => ({ def, key: (prev?.key ?? 0) + 1 }));
    setTimeout(() => document.getElementById('theme-builder')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
  };
  const [provider, setProvider] = useState('lm_studio');
  const [localOnly, setLocalOnly] = useState(true);
  const [geminiUrl, setGeminiUrl] = useState('http://127.0.0.1:8001');
  const [geminiKey, setGeminiKey] = useState('');
  const [geminiModel, setGeminiModel] = useState('flash');
  const [geminiThinkingLevel, setGeminiThinkingLevel] = useState('high');
  const [geminiStatus, setGeminiStatus] = useState<GeminiStatus | null>(null);
  const [testingGemini, setTestingGemini] = useState(false);
  const [openaiKey, setOpenaiKey] = useState('');
  const [openaiModel, setOpenaiModel] = useState('');
  // Claude API (the claude-local-api proxy) and whether video production
  // (visual planning, BuzzEdit's moods/topics/prompts) is routed through it.
  const [claudeUrl, setClaudeUrl] = useState('');
  const [claudeKey, setClaudeKey] = useState('');
  const [claudeModel, setClaudeModel] = useState('');
  const [useClaudeForProduction, setUseClaudeForProduction] = useState(false);
  // Thinking (reasoning) for local thinking models: agents on, production off.
  const [thinkingAgents, setThinkingAgents] = useState(true);
  const [thinkingProduction, setThinkingProduction] = useState(false);
  // Where the finished video goes once BuzzEdit has rendered it.
  const [outputMode, setOutputMode] = useState<'beside_recording' | 'folder' | 'buzzedit'>('beside_recording');
  const [outputDir, setOutputDir] = useState('');
  const [revealOutput, setRevealOutput] = useState(true);
  // GPU memory: idle unload delay (minutes, 0 = never) and llama.cpp stop.
  const [idleOffloadMinutes, setIdleOffloadMinutes] = useState(5);
  const [offloadLlamacpp, setOffloadLlamacpp] = useState(true);
  const [claudeStatus, setClaudeStatus] = useState<ClaudeStatus | null>(null);
  const [testingClaude, setTestingClaude] = useState(false);
  // Free stock footage (Pixabay): key + on/off switch.
  const [pixabayKey, setPixabayKey] = useState('');
  const [pixabayEnabled, setPixabayEnabled] = useState(false);
  const [stockStatus, setStockStatus] = useState<StockStatus | null>(null);
  const [syncingStock, setSyncingStock] = useState(false);
  const [lmStudioUrl, setLmStudioUrl] = useState('');
  const [lmStudioModel, setLmStudioModel] = useState('');
  const [ollamaUrl, setOllamaUrl] = useState('');
  const [ollamaModel, setOllamaModel] = useState('');
  const [llamacppUrl, setLlamacppUrl] = useState('');
  const [llamacppModel, setLlamacppModel] = useState('');
  const [tiers, setTiers] = useState<Record<string, TierSetting>>({ fast: {}, strong: {}, premium: {} });
  const [routingOpen, setRoutingOpen] = useState(false);
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

  // Channel Profiles (backend/integrations/buzzedit_settings.py channel
  // profile table -- GET/PUT /api/channel_profiles).
  const [channelProfiles, setChannelProfiles] = useState<Record<string, ChannelProfile>>({});
  const [savingProfile, setSavingProfile] = useState<string | null>(null);

  const fetchChannelProfiles = async () => {
    try {
      const data = await getJson<ChannelProfilesResponse>('/api/channel_profiles');
      setChannelProfiles(data.profiles || {});
    } catch (err) {
      console.warn('Could not fetch channel profiles', err);
    }
  };

  useEffect(() => {
    fetchChannelProfiles();
  }, []);

  const setChannelProfileField = (brand: string, patch: Partial<ChannelProfile>) =>
    setChannelProfiles((prev) => ({
      ...prev,
      [brand]: { ...prev[brand], ...patch },
    }));

  const saveChannelProfile = async (brand: string) => {
    const profile = channelProfiles[brand];
    if (!profile) return;
    setSavingProfile(brand);
    try {
      await putJson(`/api/channel_profiles/${encodeURIComponent(brand)}`, {
        genre: profile.genre,
        genre_secondary: profile.genre_secondary || null,
        density: profile.density,
        voice_preset: profile.voice_preset || 'studio_mic',
        art_style: profile.art_style || 'real',
      });
      toast(`Channel profile saved for "${brand}".`, 'success');
      await fetchChannelProfiles();
    } catch (err) {
      toast(`Could not save channel profile: ${describeError(err)}`, 'error');
    } finally {
      setSavingProfile(null);
    }
  };

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
    setGeminiUrl(str('gemini_url') || 'http://127.0.0.1:8001');
    setGeminiModel(str('gemini_model') || 'flash');
    setGeminiThinkingLevel(str('gemini_thinking_level') || 'high');
    setOpenaiModel(str('openai_model'));
    setLmStudioUrl(str('lm_studio_url'));
    setLmStudioModel(str('lm_studio_model'));
    setOllamaUrl(str('ollama_url'));
    setOllamaModel(str('ollama_model'));
    setLlamacppUrl(str('llamacpp_url'));
    setLlamacppModel(str('llamacpp_model'));
    setClaudeUrl(str('claude_url'));
    setClaudeModel(str('claude_model'));
    setUseClaudeForProduction(String(settings.produce_llm_provider || 'auto') === 'claude');
    setThinkingAgents(settings.thinking_agents !== false);
    setThinkingProduction(Boolean(settings.thinking_production));
    const mode = String(settings.produce_output_mode || 'beside_recording');
    setOutputMode(mode === 'folder' || mode === 'buzzedit' ? mode : 'beside_recording');
    setOutputDir(String(settings.produce_output_dir || ''));
    setRevealOutput(settings.produce_reveal_output !== false);
    if (typeof settings.idle_offload_seconds === 'number') setIdleOffloadMinutes(Math.round(settings.idle_offload_seconds / 60));
    setOffloadLlamacpp(Boolean(settings.idle_offload_llamacpp));
    setPixabayEnabled(Boolean(settings.pixabay_enabled));
    if (settings.web_research_enabled !== undefined) setWebResearchEnabled(Boolean(settings.web_research_enabled));
    if (settings.search_provider) setSearchProvider(String(settings.search_provider));
    if (settings.searxng_url) setSearxngUrl(String(settings.searxng_url));
    const stored = settings.tiers as Record<string, TierSetting> | undefined;
    setTiers({ fast: stored?.fast || {}, strong: stored?.strong || {}, premium: stored?.premium || {} });
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
        premium: { provider: tiers.premium?.provider || '', model: tiers.premium?.model || '' },
      },
      owner_channel_ids: ownerChannels.split(',').map((s) => s.trim()).filter(Boolean),
      web_research_enabled: webResearchEnabled,
      search_provider: searchProvider,
      searxng_url: searxngUrl.trim(),
      produce_llm_provider: useClaudeForProduction ? 'claude' : 'auto',
      gemini_thinking_level: geminiThinkingLevel,
      thinking_agents: thinkingAgents,
      thinking_production: thinkingProduction,
      produce_output_mode: outputMode,
      produce_output_dir: outputDir.trim(),
      produce_reveal_output: revealOutput,
      idle_offload_seconds: Math.max(0, Math.round(idleOffloadMinutes * 60)),
      idle_offload_llamacpp: offloadLlamacpp,
      pixabay_enabled: pixabayEnabled,
    };
    // Only send a key when one was typed: blank means "keep the stored key".
    if (geminiKey.trim()) payload.gemini_api_key = geminiKey.trim();
    if (geminiUrl.trim()) payload.gemini_url = geminiUrl.trim();
    if (openaiKey.trim()) payload.openai_api_key = openaiKey.trim();
    if (claudeKey.trim()) payload.claude_api_key = claudeKey.trim();
    if (claudeUrl.trim()) payload.claude_url = claudeUrl.trim();
    if (pixabayKey.trim()) payload.pixabay_api_key = pixabayKey.trim();
    if (geminiModel.trim()) payload.gemini_model = geminiModel.trim();
    if (geminiThinkingLevel.trim()) payload.gemini_thinking_level = geminiThinkingLevel.trim();
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
      setClaudeKey('');
      setPixabayKey('');
      await refreshSettings();
      await fetchLocalModels();
      void fetchStockStatus();
      toast(`Settings saved. Active provider: ${provider} (Strict Local: ${localOnly ? 'ON' : 'OFF'}).`, 'success');
    } catch (err) {
      toast(`Could not save settings: ${describeError(err)}`, 'error');
    } finally {
      setSaving(false);
    }
  };

  const testGeminiConnection = async () => {
    setTestingGemini(true);
    try {
      const payload: Record<string, unknown> = {};
      if (geminiKey.trim()) payload.gemini_api_key = geminiKey.trim();
      if (geminiUrl.trim()) payload.gemini_url = geminiUrl.trim();
      if (geminiModel.trim()) payload.gemini_model = geminiModel.trim();
      if (geminiThinkingLevel.trim()) payload.gemini_thinking_level = geminiThinkingLevel.trim();
      if (Object.keys(payload).length > 0) {
        await postJson('/api/settings', payload);
        setGeminiKey('');
        await refreshSettings();
      }
      const res = await getJson<GeminiStatus>('/api/gemini/status');
      setGeminiStatus(res);
    } catch (err) {
      setGeminiStatus({
        url: geminiUrl, model: geminiModel, key_set: false, online: false, is_local: true,
        auth_mode: '', models: [], message: `Could not probe Gemini: ${describeError(err)}`,
      });
    } finally {
      setTestingGemini(false);
    }
  };

  const testClaudeConnection = async () => {
    setTestingClaude(true);
    try {
      // Save the fields first so the probe uses what is on screen, not what
      // was on disk before the user started typing.
      const payload: Record<string, unknown> = {};
      if (claudeKey.trim()) payload.claude_api_key = claudeKey.trim();
      if (claudeUrl.trim()) payload.claude_url = claudeUrl.trim();
      if (claudeModel.trim()) payload.claude_model = claudeModel.trim();
      if (Object.keys(payload).length > 0) {
        await postJson('/api/settings', payload);
        setClaudeKey('');
        await refreshSettings();
      }
      const res = await getJson<ClaudeStatus>('/api/produce/claude/status');
      setClaudeStatus(res);
    } catch (err) {
      setClaudeStatus({
        url: claudeUrl, model: claudeModel, key_set: false, online: false, authorized: false,
        models: [], routed: false, message: `Could not probe the Claude proxy: ${describeError(err)}`,
      });
    } finally {
      setTestingClaude(false);
    }
  };

  const fetchStockStatus = async () => {
    try {
      setStockStatus(await getJson<StockStatus>('/api/produce/stock/status'));
    } catch (err) {
      console.warn('Could not fetch stock footage status', err);
    }
  };

  useEffect(() => {
    void fetchStockStatus();
  }, []);

  const syncPixabayKey = async () => {
    setSyncingStock(true);
    try {
      if (pixabayKey.trim()) {
        await postJson('/api/settings', { pixabay_api_key: pixabayKey.trim(), pixabay_enabled: pixabayEnabled });
        setPixabayKey('');
        await refreshSettings();
      }
      await postJson('/api/produce/stock/sync', {});
      toast('Pixabay key handed to BuzzEdit.', 'success');
    } catch (err) {
      toast(`Could not send the key to BuzzEdit: ${describeError(err)}`, 'error');
    } finally {
      await fetchStockStatus();
      setSyncingStock(false);
    }
  };

  const tierRow = (name: 'fast' | 'strong' | 'premium', description: string) => {
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
        ? GEMINI_MODELS
        : tierProv === 'openai'
        ? ['gpt-4o-mini', 'gpt-4o']
        : tierProv === 'claude'
        ? CLAUDE_MODELS
        : [];

    return (
      <div className="form-row" style={{ alignItems: 'flex-end', marginBottom: 16 }}>
        <div className="form-group" style={{ flex: '1 1 200px' }}>
          <label style={{ textTransform: 'capitalize' }}>{name} tier</label>
          <select
            className="form-control"
            aria-label={`${name} tier`}
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
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    {isActive ? (
                      <span style={{ fontSize: '0.75rem', fontWeight: 700, color: 'var(--border-highlight)', display: 'flex', alignItems: 'center', gap: 4 }}>
                        <CheckCircle2 size={14} /> Active
                      </span>
                    ) : (
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Click to activate</span>
                    )}
                    <button
                      type="button"
                      className="theme-card-tool"
                      title={t.custom ? 'Edit this theme' : 'Customise a copy of this theme'}
                      onClick={(e) => {
                        e.stopPropagation();
                        openBuilder(t);
                      }}
                    >
                      {t.custom ? <Pencil size={13} /> : <Copy size={13} />}
                    </button>
                    {t.custom && (
                      <button
                        type="button"
                        className="theme-card-tool danger"
                        title="Delete this theme"
                        onClick={(e) => {
                          e.stopPropagation();
                          if (window.confirm(`Delete the theme "${t.name}"?`)) deleteCustomTheme(t.id);
                        }}
                      >
                        <Trash2 size={13} />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Theme Builder */}
      <div className="panel-card" id="theme-builder" style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 10, marginBottom: 8 }}>
          <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0 }}>
            <Palette size={20} /> Theme Builder
          </h3>
          {!builderSeed && (
            <button type="button" className="btn btn-outline btn-compact" onClick={() => openBuilder(currentThemeDef)}>
              <Pencil size={14} /> Customise {currentThemeDef.name}
            </button>
          )}
        </div>
        <p style={{ margin: '4px 0 12px', fontSize: '0.88rem', color: 'var(--text-secondary)' }}>
          Pick the colours yourself. Start from any theme (the copy icon on a card), nudge the surfaces darker or lighter,
          and the Studio previews every change live. Saved themes join the list above and the header switcher, and stay in this browser.
        </p>
        {builderSeed ? (
          <ThemeBuilder key={builderSeed.key} seed={builderSeed.def} />
        ) : (
          <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            Click the copy icon on any theme card, or the button above, to open the builder.
          </div>
        )}
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
              aria-label="Strict Local Privacy Mode"
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
          <select className="form-control" aria-label="Selected Primary Provider" value={provider} onChange={(e) => setProvider(e.target.value)}>
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
                aria-label="LM Studio URL"
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
                aria-label="Ollama URL"
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
                aria-label="llama.cpp URL"
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

        {/* 4. Google Gemini Harness Section (Local server @ 8001 or Cloud API) */}
        <div style={{ borderTop: '1px solid #1e293b', paddingTop: 16, marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
            <strong style={{ color: '#e2e8f0', display: 'flex', alignItems: 'center', gap: 6 }}>
              <Server size={16} style={{ color: '#60a5fa' }} /> Google Gemini (Local Harness / Cloud)
            </strong>
            {geminiStatus?.online ? (
              <span className="status-badge status-completed" style={{ fontSize: '0.75rem' }}>
                ✓ {geminiStatus.auth_mode || 'Online'}
              </span>
            ) : (
              <span className="status-badge" style={{ fontSize: '0.75rem', opacity: 0.7 }}>
                {geminiStatus ? 'Not detected on port 8001' : 'Port 8001'}
              </span>
            )}
          </div>
          <div className="form-row">
            <div className="form-group" style={{ flex: '1 1 240px' }}>
              <label>Gemini Server URL</label>
              <input
                type="text"
                className="form-control"
                placeholder="http://127.0.0.1:8001"
                aria-label="Gemini Server URL"
                value={geminiUrl}
                onChange={(e) => { setGeminiUrl(e.target.value); setGeminiStatus(null); }}
              />
            </div>
            <ModelPicker
              label="Gemini Model"
              value={geminiModel}
              onChange={(m) => { setGeminiModel(m); setGeminiStatus(null); }}
              models={GEMINI_MODELS}
              placeholder="flash"
            />
            <div className="form-group" style={{ flex: '0 1 180px' }}>
              <label>Reasoning Effort</label>
              <select
                className="form-control"
                value={geminiThinkingLevel}
                onChange={(e) => { setGeminiThinkingLevel(e.target.value); setGeminiStatus(null); }}
                aria-label="Gemini Reasoning Effort Level"
              >
                <option value="low">Low (Fast ~3s)</option>
                <option value="medium">Medium (Balanced)</option>
                <option value="high">High (Deep reasoning)</option>
                <option value="max">Max (Exhaustive)</option>
              </select>
            </div>
            <div className="form-group" style={{ flex: '0 0 auto', alignSelf: 'flex-end' }}>
              <button
                type="button"
                className="btn btn-outline"
                disabled={testingGemini}
                onClick={testGeminiConnection}
              >
                {testingGemini ? 'Testing…' : 'Test connection'}
              </button>
            </div>
          </div>
          {geminiStatus && (
            <div
              style={{
                marginTop: 4,
                marginBottom: 10,
                fontSize: '0.8rem',
                padding: '4px 8px',
                borderRadius: 4,
                backgroundColor: geminiStatus.online ? 'rgba(74, 222, 128, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                color: geminiStatus.online ? '#4ade80' : '#fca5a5',
                border: `1px solid ${geminiStatus.online ? '#4ade80' : '#ef4444'}`,
              }}
            >
              {geminiStatus.online ? '✓ ' : '✕ '}
              {geminiStatus.message}
            </div>
          )}
          <div className="form-row">
            <div className="form-group" style={{ flex: '1 1 300px' }}>
              <label>
                Google Gemini Cloud API key (Optional cloud fallback)
                {settings?.gemini_api_key_set && <span style={{ marginLeft: 8, fontSize: '0.75rem', color: '#4ade80' }}>✓ key saved</span>}
              </label>
              <input
                type="password"
                className="form-control"
                placeholder={settings?.gemini_api_key_set ? 'Saved — type a new key to replace it' : 'AIzaSy… (leave blank to use local harness on 8001)'}
                aria-label="Google Gemini API key"
                value={geminiKey}
                onChange={(e) => setGeminiKey(e.target.value)}
              />
            </div>
          </div>
          <p style={{ color: '#64748b', fontSize: '0.78rem', margin: '4px 0 0' }}>
            Your local Gemini harness running at <code>http://127.0.0.1:8001</code> answers via your Antigravity CLI keyring session with personal Google OAuth (Zero API keys required). Works under Strict Local Mode. Reasoning Effort (<code>low</code>, <code>medium</code>, <code>high</code>, <code>max</code>) controls thinking depth.
          </p>
        </div>

        {/* 5. Cloud Fallback Section (Visible only when localOnly is unchecked) */}
        {!localOnly && (
          <div style={{ borderTop: '1px solid #1e293b', paddingTop: 16 }}>
            <p style={{ color: '#fca5a5', fontSize: '0.85rem', marginBottom: 12 }}>
              ⚠ Cloud providers enabled. Prompts will fall back to external servers if all local LLMs fail.
            </p>
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
                  aria-label="OpenAI API key"
                  value={openaiKey}
                  onChange={(e) => setOpenaiKey(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label>OpenAI model</label>
                <input type="text" className="form-control" placeholder="gpt-4o-mini" aria-label="OpenAI model" value={openaiModel} onChange={(e) => setOpenaiModel(e.target.value)} />
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Model Tiers */}
      <div className="panel-card">
        <h3 className="panel-title"><SettingsIcon size={20} /> Model Tiers</h3>
        <p style={{ color: '#94a3b8', margin: '0 0 20px 0' }}>
          Each persona declares a tier in its frontmatter. Fast work (tags, titles, checklists) runs on the fast tier, the rest on the strong tier, and the few that decide a video's quality -- the researcher, the script writer, the Shorts writer and the SEO manager -- on the premium tier (Claude Opus through the local Claude proxy by default; if the proxy is down the call falls back to the selected provider).
        </p>
        {tierRow('fast', 'Fast tasks: Tags, titles, checklists.')}
        {tierRow('strong', 'Heavy tasks: Direction, editing, planning.')}
        {tierRow('premium', 'Research, scripts, the session Shorts and SEO research (default: Claude, opus).')}
        <p style={{ color: '#94a3b8', margin: '12px 0 8px 0' }}>
          Model Routing overrides the tiers per kind of work (research, script, Shorts, SEO, ...): Claude, Gemma, Ollama or Gemini, with a fallback.
        </p>
        <button type="button" className="btn btn-outline" onClick={() => setRoutingOpen(true)}>Open Model Routing</button>
        <ModelRoutingWindow open={routingOpen} onClose={() => setRoutingOpen(false)} />
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
              aria-label="Enable Live Web Research"
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
            <select className="form-control" aria-label="Search Provider" value={searchProvider} onChange={(e) => setSearchProvider(e.target.value)}>
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
              aria-label="SearXNG URL"
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
              aria-label="Allow All Workflow Steps"
              style={{ width: 18, height: 18, accentColor: '#10b981' }}
            />
            <span style={{ color: allowAllSteps ? '#34d399' : '#e2e8f0' }}>
              {allowAllSteps ? 'Allow All (Continuous)' : 'Pause for Approval'}
            </span>
          </label>
        </div>
      </div>

      {/* Thinking: whether a local thinking model (Gemma 4, Qwen 3.x in LM
          Studio) reasons before it answers -- integrations/llm.py. */}
      <div className="panel-card">
        <h3 className="panel-title">
          <Brain size={20} style={{ color: '#a78bfa' }} /> Thinking (local models)
        </h3>
        <p style={{ color: '#94a3b8', margin: '0 0 16px 0' }}>
          Thinking models reason step by step before answering: better judgement, but several times slower.
          Applies to LM Studio and the local Gemini harness (port 8001); Claude and cloud providers are unaffected.
        </p>
        <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer', marginBottom: 14 }}>
          <input
            type="checkbox"
            checked={thinkingAgents}
            onChange={(e) => setThinkingAgents(e.target.checked)}
            aria-label="Agents, chat and writing"
            style={{ width: 18, height: 18, marginTop: 2, accentColor: '#a78bfa' }}
          />
          <span>
            <strong>Agents, chat and writing</strong> (recommended on)
            <br />
            <span style={{ color: '#94a3b8' }}>
              Workflow steps, the Studio Assistant, scripts, research and strategy. One call at a time, where quality matters most.
            </span>
          </span>
        </label>
        <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={thinkingProduction}
            onChange={(e) => setThinkingProduction(e.target.checked)}
            aria-label="Video production"
            style={{ width: 18, height: 18, marginTop: 2, accentColor: '#a78bfa' }}
          />
          <span>
            <strong>Video production</strong> (recommended off)
            <br />
            <span style={{ color: '#94a3b8' }}>
              Produce Video's per-window visual planning and BuzzEdit's moods, topics and picture prompts. Measured on
              gemma-4-12b: ~20 s per window off vs ~3-4 min on (a 14-minute take: ~3 min vs ~25+ min of planning), for
              slightly fuller plans.
            </span>
          </span>
        </label>

        <h4 style={{ margin: '18px 0 6px 0' }}>Save the final video</h4>
        <p style={{ color: '#94a3b8', margin: '0 0 10px 0' }}>
          Where the finished video is put once BuzzEdit has rendered it. It is named after the recording with
          <code> _final</code>; BuzzEdit's own render stays where it was for re-renders and publishing.
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
            <input type="radio" name="produce_output_mode" checked={outputMode === 'beside_recording'}
              onChange={() => setOutputMode('beside_recording')} />
            <span><strong>Next to the recording</strong> (recommended): the folder the source video came from.</span>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
            <input type="radio" name="produce_output_mode" checked={outputMode === 'folder'}
              onChange={() => setOutputMode('folder')} />
            <span>One folder for every video:</span>
            <input
              type="text"
              value={outputDir}
              onChange={(e) => setOutputDir(e.target.value)}
              placeholder="B:\youtubeProjects\final"
              disabled={outputMode !== 'folder'}
              style={{ flex: 1, minWidth: 220 }}
            />
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}>
            <input type="radio" name="produce_output_mode" checked={outputMode === 'buzzedit'}
              onChange={() => setOutputMode('buzzedit')} />
            <span>Leave it where BuzzEdit wrote it.</span>
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', marginTop: 4 }}>
            <input type="checkbox" checked={revealOutput} onChange={(e) => setRevealOutput(e.target.checked)}
              style={{ width: 18, height: 18 }} />
            <span>Open the folder in Explorer when a video is ready.</span>
          </label>
        </div>
      </div>

      {/* GPU memory: integrations/idle_offload.py. Models load on a cleared
          card and are offloaded when a task ends; these two knobs cover the
          idle window and whether llama.cpp may be stopped. */}
      <div className="panel-card">
        <h3 className="panel-title">
          <Cpu size={20} style={{ color: '#34d399' }} /> GPU memory
        </h3>
        <p style={{ color: '#94a3b8', margin: '0 0 16px 0' }}>
          Before any model loads (music, images, video, LLM) the others are ejected from the GPU, and every model is
          offloaded when a production task finishes. LM Studio, Ollama and ComfyUI reload on their next request.
        </p>
        <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer', marginBottom: 14 }}>
          <input
            type="checkbox"
            checked={offloadLlamacpp}
            onChange={(e) => setOffloadLlamacpp(e.target.checked)}
            aria-label="Also stop llama.cpp when offloading"
            style={{ width: 18, height: 18, marginTop: 2, accentColor: '#34d399' }}
          />
          <span>
            <strong>Also stop llama.cpp</strong> when offloading
            <br />
            <span style={{ color: '#94a3b8' }}>
              llama.cpp cannot unload a model without stopping its server, and the Studio cannot restart it -- it is
              BuzzCode's engine too, so BuzzCode (or you) starts it again when it is next needed.
            </span>
          </span>
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span>Unload idle models after</span>
          <input
            type="number"
            className="form-control"
            min={0}
            max={240}
            aria-label="Unload idle models after"
            value={idleOffloadMinutes}
            onChange={(e) => setIdleOffloadMinutes(Math.max(0, Number(e.target.value) || 0))}
            style={{ width: 80 }}
          />
          <span style={{ color: '#94a3b8' }}>minutes of no activity (0 = never; covers chat, which is not a production task)</span>
        </label>
      </div>

      {/* Claude API: the claude-local-api proxy (../claudeAPI), used for video
          production when the switch is on (app/api/produce_api.py). */}
      <div className="panel-card">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 12 }}>
          <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0 }}>
            <Sparkles size={20} style={{ color: '#f59e0b' }} /> Claude API (video production)
          </h3>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontWeight: 600 }}>
            <input
              type="checkbox"
              checked={useClaudeForProduction}
              onChange={(e) => setUseClaudeForProduction(e.target.checked)}
              aria-label="Use Claude for video production"
              style={{ width: 18, height: 18, accentColor: '#f59e0b' }}
            />
            <span style={{ color: useClaudeForProduction ? '#fbbf24' : '#e2e8f0' }}>
              {useClaudeForProduction ? 'Using Claude for video production' : 'Use Claude for video production'}
            </span>
          </label>
        </div>
        <p style={{ color: '#94a3b8', margin: '0 0 16px 0' }}>
          Your local <code>claude-local-api</code> proxy (Claude Code login, OpenAI-compatible). With the switch on,
          Produce Video sends its model work here instead of the local LM Studio model: the per-window visual
          planning in the Studio, and BuzzEdit's "reading the mood of each part", topics, thumbnail title and
          picture prompts. Pictures and clips are still generated by ComfyUI. If the proxy is down, the normal
          provider order takes over automatically. Also selectable as a provider or tier above.
        </p>
        <div className="form-row">
          <div className="form-group">
            <label>Proxy base URL</label>
            <input
              type="text"
              className="form-control"
              placeholder="http://127.0.0.1:8787/v1"
              aria-label="Proxy base URL"
              value={claudeUrl}
              onChange={(e) => { setClaudeUrl(e.target.value); setClaudeStatus(null); }}
            />
          </div>
          <div className="form-group">
            <label>
              Proxy API key
              {settings?.claude_api_key_set && <span style={{ marginLeft: 8, fontSize: '0.75rem', color: '#4ade80' }}>✓ key saved</span>}
            </label>
            <input
              type="password"
              className="form-control"
              placeholder={settings?.claude_api_key_set ? 'Saved — type a new key to replace it' : 'sk-local-…'}
              aria-label="Proxy API key"
              value={claudeKey}
              onChange={(e) => { setClaudeKey(e.target.value); setClaudeStatus(null); }}
            />
          </div>
          <ModelPicker
            label="Model"
            value={claudeModel}
            onChange={(v) => { setClaudeModel(v); setClaudeStatus(null); }}
            models={claudeStatus?.models?.length ? claudeStatus.models : CLAUDE_MODELS}
            placeholder="sonnet"
            allowEmpty
            emptyLabel="sonnet (default)"
          />
          <div className="form-group" style={{ flex: '0 0 auto', alignSelf: 'flex-end' }}>
            <button
              type="button"
              className="btn btn-outline"
              disabled={testingClaude}
              onClick={testClaudeConnection}
            >
              {testingClaude ? 'Testing…' : 'Test connection'}
            </button>
          </div>
        </div>
        {claudeStatus && (
          <div
            style={{
              marginTop: 4,
              fontSize: '0.8rem',
              padding: '4px 8px',
              borderRadius: 4,
              backgroundColor: claudeStatus.authorized ? 'rgba(74, 222, 128, 0.1)' : claudeStatus.online ? 'rgba(245, 158, 11, 0.1)' : 'rgba(239, 68, 68, 0.1)',
              color: claudeStatus.authorized ? '#4ade80' : claudeStatus.online ? '#f59e0b' : '#fca5a5',
              border: `1px solid ${claudeStatus.authorized ? '#4ade80' : claudeStatus.online ? '#f59e0b' : '#ef4444'}`,
            }}
          >
            {claudeStatus.authorized ? '✓ ' : claudeStatus.online ? '⚠ ' : '✕ '}
            {claudeStatus.message}
            {claudeStatus.routed ? ' Video production is routed here.' : ''}
          </div>
        )}
        <p style={{ color: '#64748b', fontSize: '0.78rem', margin: '10px 0 0' }}>
          Start the proxy with <code>start-server.bat start</code> in the claudeAPI folder; make a key with
          <code> npm run keys -- create studio</code>. Note: prompts leave this PC through your Claude login even
          under Strict Local Mode when this switch is on.
        </p>
      </div>

      {/* Stock footage (Pixabay): the key is handed to BuzzEdit, which does the
          search/download when a beat ComfyUI could not make falls back to stock. */}
      <div className="panel-card">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 12 }}>
          <h3 className="panel-title" style={{ margin: 0, border: 'none', padding: 0 }}>
            <Film size={20} style={{ color: '#2dd4bf' }} /> Stock footage (Pixabay)
          </h3>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontWeight: 600 }}>
            <input
              type="checkbox"
              checked={pixabayEnabled}
              onChange={(e) => setPixabayEnabled(e.target.checked)}
              aria-label="Use Pixabay stock footage"
              style={{ width: 18, height: 18, accentColor: '#2dd4bf' }}
            />
            <span style={{ color: pixabayEnabled ? '#5eead4' : '#e2e8f0' }}>
              {pixabayEnabled ? 'Pixabay stock footage ON' : 'Use Pixabay stock footage'}
            </span>
          </label>
        </div>
        <p style={{ color: '#94a3b8', margin: '0 0 16px 0' }}>
          Free photos and clips from Pixabay for any visual ComfyUI cannot make. With the switch on, every project's
          "Free stock fallback" starts on (a project can still turn it off in its Produce Video panel). The key is
          passed to BuzzEdit, which does the searching and downloading.
        </p>
        <div className="form-row">
          <div className="form-group">
            <label>
              Pixabay API key
              {settings?.pixabay_api_key_set && <span style={{ marginLeft: 8, fontSize: '0.75rem', color: '#4ade80' }}>✓ key saved</span>}
            </label>
            <input
              type="password"
              className="form-control"
              placeholder={settings?.pixabay_api_key_set ? 'Saved — type a new key to replace it' : '12345678-abcdef…'}
              aria-label="Pixabay API key"
              value={pixabayKey}
              onChange={(e) => setPixabayKey(e.target.value)}
            />
          </div>
          <div className="form-group" style={{ flex: '0 0 auto', alignSelf: 'flex-end' }}>
            <button
              type="button"
              className="btn btn-outline"
              disabled={syncingStock || (!pixabayKey.trim() && !settings?.pixabay_api_key_set)}
              onClick={syncPixabayKey}
            >
              {syncingStock ? 'Sending…' : 'Send key to BuzzEdit now'}
            </button>
          </div>
        </div>
        {stockStatus && (
          <p style={{ color: '#64748b', fontSize: '0.78rem', margin: '6px 0 0' }}>
            BuzzEdit: {stockStatus.buzzedit === null
              ? 'offline (the key is sent again before each render).'
              : stockStatus.buzzedit.pixabay_api_key_set
              ? `holds a Pixabay key (${stockStatus.buzzedit.pixabay_api_key || '••••'}).`
              : 'has no Pixabay key yet — save, then send it.'}
          </p>
        )}
      </div>

      <SoundEffectsCard />

      <MotionGalleryCard />

      <InstagramSettingsCard />

      {/* Your Channels */}
      <div className="panel-card">
        <h3 className="panel-title"><SettingsIcon size={20} /> Your Channels</h3>
        <div className="form-group" style={{ marginBottom: 20 }}>
          <label>Owned YouTube channel ids</label>
          <input
            type="text"
            className="form-control"
            placeholder="UCxxxx, UCyyyy"
            aria-label="Owned YouTube channel ids"
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

      {/* Channel Profiles -- per-brand genre/density/voice defaults, the base
          layer produce_video's settings resolve on top of
          (backend/integrations/buzzedit_settings.py, /api/channel_profiles). */}
      <div className="panel-card" style={{ marginTop: 20 }}>
        <h3 className="panel-title"><Palette size={20} /> Channel Profiles</h3>
        <p style={{ margin: '4px 0 16px', fontSize: '0.88rem', color: 'var(--text-secondary)' }}>
          Each brand's default genre, secondary genre, visual density, and voice preset for BuzzEdit
          renders. A project can still override these for one video from its Produce Video panel.
        </p>
        {Object.keys(channelProfiles).length === 0 ? (
          <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Loading channel profiles…</div>
        ) : (
          Object.keys(channelProfiles)
            .sort((a, b) => {
              const order = ['life3baje', 'raat3baje', 'khayal3baje', 'beyond3baje', 'originals'];
              const ia = order.indexOf(a);
              const ib = order.indexOf(b);
              if (ia === -1 && ib === -1) return a.localeCompare(b);
              if (ia === -1) return 1;
              if (ib === -1) return -1;
              return ia - ib;
            })
            .map((brand) => {
              const profile = channelProfiles[brand];
              return (
                <div
                  key={brand}
                  className="form-row"
                  style={{ alignItems: 'flex-end', marginBottom: 12, flexWrap: 'wrap', gap: 10 }}
                >
                  <div className="form-group" style={{ flex: '0 0 130px' }}>
                    <label style={{ textTransform: 'capitalize' }}>{brand}</label>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Brand key</div>
                  </div>
                  <div className="form-group" style={{ flex: '1 1 150px' }}>
                    <label>Genre</label>
                    <select
                      className="form-control"
                      aria-label={`Genre for ${brand}`}
                      value={profile.genre}
                      onChange={(e) => setChannelProfileField(brand, { genre: e.target.value })}
                    >
                      {GENRES.map((g) => (
                        <option key={g} value={g}>{g}</option>
                      ))}
                    </select>
                  </div>
                  <div className="form-group" style={{ flex: '1 1 150px' }}>
                    <label>Secondary genre</label>
                    <select
                      className="form-control"
                      aria-label={`Secondary genre for ${brand}`}
                      value={profile.genre_secondary || ''}
                      onChange={(e) => setChannelProfileField(brand, { genre_secondary: e.target.value || null })}
                    >
                      <option value="">None</option>
                      {GENRES.map((g) => (
                        <option key={g} value={g}>{g}</option>
                      ))}
                    </select>
                  </div>
                  <div className="form-group" style={{ flex: '1 1 120px' }}>
                    <label>Density</label>
                    <select
                      className="form-control"
                      aria-label={`Density for ${brand}`}
                      value={profile.density}
                      onChange={(e) => setChannelProfileField(brand, { density: e.target.value })}
                    >
                      {DENSITIES.map((d) => (
                        <option key={d} value={d}>{d}</option>
                      ))}
                    </select>
                  </div>
                  <div className="form-group" style={{ flex: '1 1 140px' }}>
                    <label>Voice preset</label>
                    <select
                      className="form-control"
                      aria-label={`Voice preset for ${brand}`}
                      value={profile.voice_preset || 'studio_mic'}
                      onChange={(e) => setChannelProfileField(brand, { voice_preset: e.target.value })}
                    >
                      {VOICE_PRESETS.map((v) => (
                        <option key={v} value={v}>{v}</option>
                      ))}
                    </select>
                  </div>
                  <div className="form-group" style={{ flex: '1 1 200px' }} title="The medium every picture, clip, thumbnail scene and text card of this channel is made in. A project can pick its own.">
                    <label>Art style</label>
                    <select
                      className="form-control"
                      aria-label={`Art style for ${brand}`}
                      value={profile.art_style || 'real'}
                      onChange={(e) => setChannelProfileField(brand, { art_style: e.target.value })}
                    >
                      {ART_STYLES.map((s) => (
                        <option key={s.id} value={s.id}>{s.label}</option>
                      ))}
                    </select>
                  </div>
                  <div className="form-group" style={{ flex: '0 0 auto' }}>
                    <button
                      type="button"
                      className="btn btn-outline"
                      disabled={savingProfile === brand}
                      onClick={() => saveChannelProfile(brand)}
                    >
                      {savingProfile === brand ? 'Saving…' : 'Save'}
                    </button>
                  </div>
                </div>
              );
            })
        )}
      </div>
    </form>
  );
}
