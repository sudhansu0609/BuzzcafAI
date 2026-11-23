import { useEffect, useMemo, useRef, useState } from 'react';
import { Check, ClipboardCopy, ClipboardPaste, Moon, Palette, RotateCcw, Save, Sun } from 'lucide-react';
import { useTheme } from '../state/ThemeContext';
import {
  deriveTokens,
  luminance,
  newCustomThemeId,
  normalizeHex,
  parseThemeJson,
  shade,
  type ThemeColors,
  type ThemeDefinition,
} from '../lib/theme';

interface Props {
  /** Theme to start from. A custom theme is edited in place; a preset is copied. */
  seed: ThemeDefinition;
}

type ColorKey = keyof ThemeColors;

const SURFACE_KEYS: ColorKey[] = ['bg', 'sidebar', 'card', 'border'];

const FIELDS: { key: ColorKey; label: string; hint: string; advanced?: boolean }[] = [
  { key: 'bg', label: 'Background', hint: 'The page behind everything' },
  { key: 'sidebar', label: 'Sidebar', hint: 'Left navigation rail and header' },
  { key: 'card', label: 'Cards', hint: 'Panels, dropdowns, inputs' },
  { key: 'border', label: 'Borders', hint: 'Card outlines and dividers' },
  { key: 'text', label: 'Text', hint: 'Headings and main copy' },
  { key: 'accent', label: 'Accent', hint: 'Buttons, links, gradient start' },
  { key: 'accentSecondary', label: 'Accent 2', hint: 'Highlights, active menu, gradient end' },
  { key: 'textSecondary', label: 'Secondary text', hint: 'Labels and descriptions (auto when blank)', advanced: true },
  { key: 'textMuted', label: 'Muted text', hint: 'Hints and timestamps (auto when blank)', advanced: true },
];

function contrast(a: string, b: string): number {
  const la = luminance(a);
  const lb = luminance(b);
  const [hi, lo] = la > lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

function seedName(seed: ThemeDefinition): string {
  return seed.custom ? seed.name : `${seed.name} (mine)`;
}

export default function ThemeBuilder({ seed }: Props) {
  const { themes, preview, saveCustomTheme, theme, previewing } = useTheme();
  const previewRef = useRef(preview);
  previewRef.current = preview;
  const [editingId, setEditingId] = useState<string>(seed.custom ? seed.id : newCustomThemeId());
  const [name, setName] = useState(seedName(seed));
  const [colors, setColors] = useState<ThemeColors>({ ...seed.colors });
  const [baseId, setBaseId] = useState<string>(seed.id);
  const [live, setLive] = useState(true);
  const [dirty, setDirty] = useState(false);
  const [advanced, setAdvanced] = useState(Boolean(seed.colors.textSecondary || seed.colors.textMuted));
  const [importOpen, setImportOpen] = useState(false);
  const [importText, setImportText] = useState('');
  const [note, setNote] = useState<string | null>(null);
  const hexDrafts = useRef<Partial<Record<ColorKey, string>>>({});
  const [, bump] = useState(0);

  const tokens = useMemo(() => deriveTokens(colors), [colors]);
  const textContrast = contrast(colors.text, colors.card);
  const accentContrast = contrast(tokens['--text-on-accent'], colors.accent);
  const isLight = luminance(colors.bg) > 0.4;

  // Live preview while the draft differs from what is saved.
  useEffect(() => {
    if (live && dirty) preview(colors);
    else if (!live && dirty) preview(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [colors, live, dirty]);

  // Leaving the page (or switching seed) ends the preview.
  useEffect(() => () => previewRef.current(null), []);

  const update = (key: ColorKey, value: string) => {
    setColors((c) => ({ ...c, [key]: value }));
    setDirty(true);
    setNote(null);
  };

  const clearOptional = (key: ColorKey) => {
    setColors((c) => {
      const next = { ...c };
      delete next[key];
      return next;
    });
    setDirty(true);
  };

  const nudgeSurfaces = (amount: number) => {
    setColors((c) => {
      const next = { ...c };
      for (const k of SURFACE_KEYS) next[k] = shade(c[k] as string, amount);
      return next;
    });
    setDirty(true);
    setNote(null);
  };

  const loadFrom = (id: string) => {
    const t = themes.find((x) => x.id === id);
    if (!t) return;
    setBaseId(id);
    setColors({ ...t.colors });
    setAdvanced(Boolean(t.colors.textSecondary || t.colors.textMuted));
    if (!t.custom || t.id !== editingId) setName(seedName(t));
    setDirty(true);
    setNote(null);
  };

  const reset = () => {
    preview(null);
    setColors({ ...seed.colors });
    setName(seedName(seed));
    setBaseId(seed.id);
    setDirty(false);
    setNote(null);
  };

  const buildDef = (): ThemeDefinition => ({
    id: editingId,
    name: name.trim() || 'Custom theme',
    category: 'custom',
    description: `Built in the Theme Builder from ${themes.find((t) => t.id === baseId)?.name ?? 'scratch'}.`,
    iconName: 'Palette',
    colors: { ...colors },
    custom: true,
  });

  const save = () => {
    const def = buildDef();
    preview(null);
    saveCustomTheme(def);
    setDirty(false);
    setNote(`Saved "${def.name}" and switched to it.`);
  };

  const saveAsNew = () => {
    const id = newCustomThemeId();
    setEditingId(id);
    const def = { ...buildDef(), id };
    preview(null);
    saveCustomTheme(def);
    setDirty(false);
    setNote(`Saved a copy as "${def.name}".`);
  };

  const copyJson = async () => {
    const def = buildDef();
    const text = JSON.stringify(def, null, 2);
    try {
      await navigator.clipboard.writeText(text);
      setNote('Theme JSON copied to the clipboard.');
    } catch {
      setImportText(text);
      setImportOpen(true);
      setNote('Clipboard unavailable: the JSON is in the box below.');
    }
  };

  const importJson = () => {
    const def = parseThemeJson(importText);
    if (!def) {
      setNote('That is not a theme JSON (needs bg, sidebar, card, border, text, accent, accentSecondary).');
      return;
    }
    setColors(def.colors);
    setName(def.name);
    setAdvanced(Boolean(def.colors.textSecondary || def.colors.textMuted));
    setDirty(true);
    setImportOpen(false);
    setNote('Imported. Save to keep it.');
  };

  const isEditingSaved = themes.some((t) => t.id === editingId);

  return (
    <div className="theme-builder">
      <div className="theme-builder-toolbar">
        <div className="form-group" style={{ flex: '1 1 200px', margin: 0 }}>
          <label>Theme name</label>
          <input
            className="form-control"
            value={name}
            maxLength={40}
            onChange={(e) => {
              setName(e.target.value);
              setDirty(true);
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') e.preventDefault();
            }}
          />
        </div>
        <div className="form-group" style={{ flex: '1 1 200px', margin: 0 }}>
          <label>Start from</label>
          <select className="form-control" value={baseId} onChange={(e) => loadFrom(e.target.value)}>
            <optgroup label="Presets">
              {themes.filter((t) => !t.custom).map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </optgroup>
            {themes.some((t) => t.custom) && (
              <optgroup label="My themes">
                {themes.filter((t) => t.custom).map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.name}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
        </div>
        <div className="form-group" style={{ flex: '0 0 auto', margin: 0 }}>
          <label>Surfaces</label>
          <div style={{ display: 'flex', gap: 6 }}>
            <button type="button" className="btn btn-outline btn-compact" onClick={() => nudgeSurfaces(-0.025)} title="Darken background, sidebar, cards and borders together">
              <Moon size={14} /> Darker
            </button>
            <button type="button" className="btn btn-outline btn-compact" onClick={() => nudgeSurfaces(0.025)} title="Lighten background, sidebar, cards and borders together">
              <Sun size={14} /> Lighter
            </button>
          </div>
        </div>
      </div>

      <div className="theme-builder-body">
        <div className="theme-color-list">
          {FIELDS.filter((f) => !f.advanced || advanced).map((f) => {
            const value = colors[f.key];
            const shown = value ? normalizeHex(value) : '';
            const draft = hexDrafts.current[f.key];
            return (
              <div className="theme-color-row" key={f.key}>
                <label className="theme-color-swatch" title={`Pick ${f.label.toLowerCase()}`}>
                  <input
                    type="color"
                    value={shown || (f.key === 'textSecondary' ? tokens['--text-secondary'] : f.key === 'textMuted' ? tokens['--text-muted'] : '#000000')}
                    onChange={(e) => update(f.key, e.target.value)}
                  />
                  <span style={{ background: shown || (f.key === 'textSecondary' ? tokens['--text-secondary'] : tokens['--text-muted']) }} />
                </label>
                <div className="theme-color-meta">
                  <div className="theme-color-label">{f.label}</div>
                  <div className="theme-color-hint">{f.hint}</div>
                </div>
                <input
                  className="form-control theme-color-hex"
                  value={draft ?? shown}
                  placeholder={f.advanced ? 'auto' : '#000000'}
                  spellCheck={false}
                  onChange={(e) => {
                    const v = e.target.value;
                    hexDrafts.current[f.key] = v;
                    bump((n) => n + 1);
                    if (/^#?[0-9a-f]{6}$/i.test(v.trim())) {
                      update(f.key, normalizeHex(v));
                    } else if (f.advanced && v.trim() === '') {
                      clearOptional(f.key);
                    }
                  }}
                  onBlur={() => {
                    delete hexDrafts.current[f.key];
                    bump((n) => n + 1);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') e.preventDefault();
                  }}
                />
                {f.advanced && value && (
                  <button type="button" className="theme-color-clear" onClick={() => clearOptional(f.key)} title="Back to automatic">
                    auto
                  </button>
                )}
              </div>
            );
          })}
          <button type="button" className="theme-builder-link" onClick={() => setAdvanced((a) => !a)}>
            {advanced ? 'Hide' : 'Show'} secondary & muted text
          </button>
        </div>

        <div className="theme-builder-preview" style={{ background: tokens['--bg-app'], borderColor: tokens['--border-card'] }}>
          <div className="theme-builder-preview-sidebar" style={{ background: tokens['--bg-sidebar'], borderRight: `1px solid ${tokens['--border-subtle']}` }}>
            <div className="theme-builder-preview-brand" style={{ backgroundImage: tokens['--sidebar-brand-gradient'] }}>
              Buzzcaf
            </div>
            <div className="theme-builder-preview-menu" style={{ background: tokens['--active-menu-bg'], borderLeft: `3px solid ${tokens['--active-menu-border']}`, color: tokens['--active-menu-text'] }}>
              Projects
            </div>
            <div className="theme-builder-preview-menu" style={{ color: tokens['--text-secondary'] }}>
              Scheduler
            </div>
            <div className="theme-builder-preview-menu" style={{ color: tokens['--text-secondary'] }}>
              Settings
            </div>
          </div>
          <div className="theme-builder-preview-main">
            <div className="theme-builder-preview-card" style={{ background: tokens['--bg-card'], borderColor: tokens['--border-card'], boxShadow: tokens['--card-shadow'] }}>
              <div style={{ color: tokens['--text-primary'], fontWeight: 600, fontSize: '0.9rem' }}>Raat 3 Baje · Episode 7</div>
              <div style={{ color: tokens['--text-secondary'], fontSize: '0.78rem', marginTop: 4 }}>Script written, visuals planned. Render queued.</div>
              <div style={{ color: tokens['--text-muted'], fontSize: '0.7rem', marginTop: 6 }}>Updated 3 minutes ago</div>
              <div style={{ display: 'flex', gap: 8, marginTop: 10, flexWrap: 'wrap' }}>
                <span className="theme-builder-preview-btn" style={{ background: tokens['--accent-gradient'], color: tokens['--text-on-accent'] }}>
                  Produce
                </span>
                <span className="theme-builder-preview-btn" style={{ border: `1px solid ${tokens['--border-card']}`, color: tokens['--text-primary'] }}>
                  Open
                </span>
                <span className="theme-builder-preview-pill" style={{ background: tokens['--bg-pill'], color: tokens['--text-muted'], border: `1px solid ${tokens['--border-card']}` }}>
                  long form
                </span>
              </div>
            </div>
            <div className="theme-builder-preview-card" style={{ background: tokens['--chat-agent-bg'], borderColor: tokens['--chat-agent-border'], color: tokens['--chat-agent-text'], fontSize: '0.78rem' }}>
              <span style={{ color: tokens['--accent-primary'], fontWeight: 600 }}>WriterAgent</span> · Draft section 3 is ready for review.
            </div>
            <div className="theme-builder-contrast">
              <span className={textContrast >= 4.5 ? 'ok' : 'warn'} title="Text on cards (WCAG AA wants 4.5)">
                text {textContrast.toFixed(1)}:1
              </span>
              <span className={accentContrast >= 3 ? 'ok' : 'warn'} title="Button label on the accent (3 is the floor)">
                button {accentContrast.toFixed(1)}:1
              </span>
              <span>{isLight ? 'light theme' : 'dark theme'}</span>
            </div>
          </div>
        </div>
      </div>

      <div className="theme-builder-actions">
        <label className="theme-builder-live">
          <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} /> Preview live on the whole Studio
        </label>
        <div style={{ flex: 1 }} />
        <button type="button" className="btn btn-outline btn-compact" onClick={() => setImportOpen((o) => !o)}>
          <ClipboardPaste size={14} /> Import JSON
        </button>
        <button type="button" className="btn btn-outline btn-compact" onClick={copyJson}>
          <ClipboardCopy size={14} /> Copy JSON
        </button>
        <button type="button" className="btn btn-outline btn-compact" onClick={reset} disabled={!dirty}>
          <RotateCcw size={14} /> Reset
        </button>
        {isEditingSaved && (
          <button type="button" className="btn btn-outline btn-compact" onClick={saveAsNew}>
            <Palette size={14} /> Save as new
          </button>
        )}
        <button type="button" className="btn btn-compact" onClick={save}>
          {isEditingSaved ? <Save size={14} /> : <Check size={14} />} {isEditingSaved ? 'Save changes' : 'Save theme'}
        </button>
      </div>

      {importOpen && (
        <div style={{ marginTop: 10 }}>
          <textarea
            className="form-control"
            rows={6}
            value={importText}
            onChange={(e) => setImportText(e.target.value)}
            placeholder='{"name": "My theme", "colors": {"bg": "#111319", "sidebar": "#181a22", "card": "#1c1f28", "border": "#2b2f3c", "text": "#eef0f5", "accent": "#a99bd9", "accentSecondary": "#e26d85"}}'
            style={{ fontFamily: 'monospace', fontSize: '0.78rem' }}
          />
          <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
            <button type="button" className="btn btn-compact" onClick={importJson}>
              Load into the builder
            </button>
            <button type="button" className="btn btn-outline btn-compact" onClick={() => setImportOpen(false)}>
              Close
            </button>
          </div>
        </div>
      )}

      {note && (
        <p style={{ margin: '10px 0 0', fontSize: '0.82rem', color: 'var(--text-secondary)' }}>{note}</p>
      )}
      {dirty && live && previewing && theme !== editingId && (
        <p style={{ margin: '6px 0 0', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
          You are seeing the draft. Save to keep it, or Reset to go back to your active theme.
        </p>
      )}
    </div>
  );
}
