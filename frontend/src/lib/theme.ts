export type PresetThemeId =
  | 'dark'
  | 'dusk_deep'
  | 'dusk'
  | 'light'
  | 'nordic'
  | 'slate'
  | 'slate_deep'
  | 'espresso'
  | 'cyberpunk'
  | 'sunset'
  | 'solarized_green'
  | 'mint_light';

/** A preset id, or `custom_<n>` for a theme built in the Theme Builder. */
export type ThemeId = PresetThemeId | (string & {});

export type ThemeCategory = 'dark' | 'light' | 'semi-dark' | 'minimalist' | 'funky' | 'custom';

export interface ThemeColors {
  bg: string;
  sidebar: string;
  card: string;
  border: string;
  text: string;
  accent: string;
  accentSecondary: string;
  /** Optional: derived from `text` and `bg` when absent. */
  textSecondary?: string;
  textMuted?: string;
}

export type ThemeIconName =
  | 'Moon'
  | 'Sun'
  | 'Feather'
  | 'Layers'
  | 'Coffee'
  | 'Zap'
  | 'Sunset'
  | 'Sparkles'
  | 'Leaf'
  | 'Palette';

export interface ThemeDefinition {
  id: ThemeId;
  name: string;
  category: ThemeCategory;
  description: string;
  iconName: ThemeIconName;
  colors: ThemeColors;
  /** True for themes built in the Theme Builder (stored in localStorage). */
  custom?: boolean;
}

export const THEME_STORAGE_KEY = 'buzzcaf_studio_theme';
export const CUSTOM_THEMES_STORAGE_KEY = 'buzzcaf_studio_custom_themes';
export const CUSTOM_THEME_ATTR = 'custom';
export const DEFAULT_THEME_ID: ThemeId = 'dark';

export const THEMES: ThemeDefinition[] = [
  {
    id: 'dark',
    name: 'Studio Dark',
    category: 'dark',
    description: 'Original Buzzcaf studio cyberpunk darkroom with rose & violet gradients.',
    iconName: 'Moon',
    colors: {
      bg: '#08090d',
      sidebar: '#0e1017',
      card: '#12141d',
      border: '#1e2230',
      text: '#f1f5f9',
      accent: '#a78bfa',
      accentSecondary: '#f43f5e',
    },
  },
  {
    id: 'dusk_deep',
    name: 'Studio Dusk Deep',
    category: 'dark',
    description: 'Between Dusk and Dark: deeper charcoal surfaces, same soft lavender & rose accents.',
    iconName: 'Moon',
    colors: {
      bg: '#111319',
      sidebar: '#181a22',
      card: '#1c1f28',
      border: '#2b2f3c',
      text: '#eef0f5',
      accent: '#a99bd9',
      accentSecondary: '#e26d85',
    },
  },
  {
    id: 'dusk',
    name: 'Studio Dusk',
    category: 'dark',
    description: 'Studio Dark, a few steps lighter and softer: charcoal-slate surfaces with muted lavender & rose accents.',
    iconName: 'Moon',
    colors: {
      bg: '#1a1c26',
      sidebar: '#22252f',
      card: '#262a36',
      border: '#363b4b',
      text: '#f1f3f8',
      accent: '#a99bd9',
      accentSecondary: '#e26d85',
    },
  },
  {
    id: 'light',
    name: 'Studio Light',
    category: 'light',
    description: 'Crisp, high-contrast modern studio light aesthetic with cool slate tones.',
    iconName: 'Sun',
    colors: {
      bg: '#f8fafc',
      sidebar: '#ffffff',
      card: '#ffffff',
      border: '#e2e8f0',
      text: '#0f172a',
      accent: '#8b5cf6',
      accentSecondary: '#f43f5e',
    },
  },
  {
    id: 'nordic',
    name: 'Nordic Paper',
    category: 'minimalist',
    description: 'Scandinavian minimalist monochrome. Warm paper white, obsidian text, distraction-free.',
    iconName: 'Feather',
    colors: {
      bg: '#fafaf9',
      sidebar: '#f5f5f4',
      card: '#ffffff',
      border: '#e7e5e4',
      text: '#1c1917',
      accent: '#44403c',
      accentSecondary: '#78716c',
    },
  },
  {
    id: 'slate',
    name: 'Slate Midnight',
    category: 'semi-dark',
    description: 'Developer / Linear semi-dark aesthetic. Deep navy slate with electric indigo & cyan highlights.',
    iconName: 'Layers',
    colors: {
      bg: '#0f172a',
      sidebar: '#1e293b',
      card: '#1e293b',
      border: '#334155',
      text: '#f8fafc',
      accent: '#6366f1',
      accentSecondary: '#38bdf8',
    },
  },
  {
    id: 'slate_deep',
    name: 'Slate Deep',
    category: 'semi-dark',
    description: 'Slate Midnight, a step darker: inkier navy surfaces with the same indigo & cyan highlights.',
    iconName: 'Layers',
    colors: {
      bg: '#0a1020',
      sidebar: '#161f31',
      card: '#161f31',
      border: '#293649',
      text: '#f8fafc',
      accent: '#6366f1',
      accentSecondary: '#38bdf8',
    },
  },
  {
    id: 'espresso',
    name: 'Espresso Cafe',
    category: 'semi-dark',
    description: 'Warm roasted coffee tones crafted for Buzzcaf. Rich dark cocoa, mocha, caramel & terracotta.',
    iconName: 'Coffee',
    colors: {
      bg: '#181412',
      sidebar: '#231d1a',
      card: '#29221f',
      border: '#3e342f',
      text: '#faf5f0',
      accent: '#f59e0b',
      accentSecondary: '#ea580c',
    },
  },
  {
    id: 'cyberpunk',
    name: 'Cyberpunk Neon',
    category: 'funky',
    description: 'Electric retrowave & synthwave energy. Deep abyss, vivid neon pink & electric cyan.',
    iconName: 'Zap',
    colors: {
      bg: '#090514',
      sidebar: '#110a26',
      card: '#160d33',
      border: '#2e1b60',
      text: '#ffffff',
      accent: '#ec4899',
      accentSecondary: '#06b6d4',
    },
  },
  {
    id: 'sunset',
    name: 'Sunset Aura',
    category: 'funky',
    description: 'Modern twilight glow. Deep plum background, luminous peach, coral & magenta gradients.',
    iconName: 'Sunset',
    colors: {
      bg: '#131124',
      sidebar: '#1c1836',
      card: '#241f45',
      border: '#3c346e',
      text: '#fdf4ff',
      accent: '#fb923c',
      accentSecondary: '#f43f5e',
    },
  },
  {
    id: 'solarized_green',
    name: 'Solarized Emerald',
    category: 'semi-dark',
    description: 'Deep forest obsidian with vivid emerald-to-cyan aurora gradients.',
    iconName: 'Sparkles',
    colors: {
      bg: '#051b17',
      sidebar: '#08241f',
      card: '#0c2e27',
      border: '#1a5649',
      text: '#ecfdf5',
      accent: '#10b981',
      accentSecondary: '#06b6d4',
    },
  },
  {
    id: 'mint_light',
    name: 'Sage Mint Light',
    category: 'light',
    description: 'Refreshing botanical light mode with soft sage canvas & crisp mint accents.',
    iconName: 'Leaf',
    colors: {
      bg: '#f2f8f5',
      sidebar: '#ffffff',
      card: '#ffffff',
      border: '#d0e4d9',
      text: '#0f291e',
      accent: '#059669',
      accentSecondary: '#0d9488',
    },
  },
];

/* ==========================================================================
   Colour helpers (hex in, hex out)
   ========================================================================== */

type RGB = [number, number, number];

export function normalizeHex(input: string, fallback = '#000000'): string {
  const s = (input || '').trim().replace(/^#/, '');
  if (/^[0-9a-f]{6}$/i.test(s)) return `#${s.toLowerCase()}`;
  if (/^[0-9a-f]{3}$/i.test(s)) {
    return `#${s
      .split('')
      .map((c) => c + c)
      .join('')
      .toLowerCase()}`;
  }
  return fallback;
}

function hexToRgb(hex: string): RGB {
  const h = normalizeHex(hex).slice(1);
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

function rgbToHex([r, g, b]: RGB): string {
  const c = (v: number) => Math.max(0, Math.min(255, Math.round(v))).toString(16).padStart(2, '0');
  return `#${c(r)}${c(g)}${c(b)}`;
}

/** Relative luminance 0..1 (WCAG). */
export function luminance(hex: string): number {
  const [r, g, b] = hexToRgb(hex).map((v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function isLightColor(hex: string): boolean {
  return luminance(hex) > 0.4;
}

/** Linear blend of `a` toward `b`; t=0 gives a, t=1 gives b. */
export function mix(a: string, b: string, t: number): string {
  const A = hexToRgb(a);
  const B = hexToRgb(b);
  const k = Math.max(0, Math.min(1, t));
  return rgbToHex([A[0] + (B[0] - A[0]) * k, A[1] + (B[1] - A[1]) * k, A[2] + (B[2] - A[2]) * k]);
}

/** Shift lightness by `amount` (-1..1) in HSL space, keeping the hue. */
export function shade(hex: string, amount: number): string {
  const [r, g, b] = hexToRgb(hex).map((v) => v / 255);
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let h = 0;
  let s = 0;
  const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r:
        h = (g - b) / d + (g < b ? 6 : 0);
        break;
      case g:
        h = (b - r) / d + 2;
        break;
      default:
        h = (r - g) / d + 4;
    }
    h /= 6;
  }
  const nl = Math.max(0, Math.min(1, l + amount));
  const hue2rgb = (p: number, q: number, t: number) => {
    let tt = t;
    if (tt < 0) tt += 1;
    if (tt > 1) tt -= 1;
    if (tt < 1 / 6) return p + (q - p) * 6 * tt;
    if (tt < 1 / 2) return q;
    if (tt < 2 / 3) return p + (q - p) * (2 / 3 - tt) * 6;
    return p;
  };
  let nr: number;
  let ng: number;
  let nb: number;
  if (s === 0) {
    nr = ng = nb = nl;
  } else {
    const q = nl < 0.5 ? nl * (1 + s) : nl + s - nl * s;
    const p = 2 * nl - q;
    nr = hue2rgb(p, q, h + 1 / 3);
    ng = hue2rgb(p, q, h);
    nb = hue2rgb(p, q, h - 1 / 3);
  }
  return rgbToHex([nr * 255, ng * 255, nb * 255]);
}

function rgba(hex: string, alpha: number): string {
  const [r, g, b] = hexToRgb(hex);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/* ==========================================================================
   Token derivation: 7 (or 9) picked colours -> the full CSS variable set
   ========================================================================== */

export const THEME_TOKEN_NAMES = [
  '--bg-app',
  '--bg-sidebar',
  '--bg-header',
  '--bg-card',
  '--bg-card-hover',
  '--bg-subcard',
  '--bg-input',
  '--bg-pill',
  '--bg-code',
  '--border-subtle',
  '--border-card',
  '--border-hover',
  '--border-highlight',
  '--text-primary',
  '--text-secondary',
  '--text-muted',
  '--text-on-accent',
  '--accent-primary',
  '--accent-secondary',
  '--accent-gradient',
  '--accent-gradient-hover',
  '--sidebar-brand-gradient',
  '--active-menu-bg',
  '--active-menu-border',
  '--active-menu-text',
  '--chat-agent-bg',
  '--chat-agent-border',
  '--chat-agent-text',
  '--card-shadow',
  '--modal-overlay',
  '--scrollbar-thumb',
  '--scrollbar-track',
  '--logo-on-light',
  '--logo-on-dark',
] as const;

export type ThemeTokens = Record<(typeof THEME_TOKEN_NAMES)[number], string>;

export function deriveTokens(colors: ThemeColors): ThemeTokens {
  const bg = normalizeHex(colors.bg, '#08090d');
  const sidebar = normalizeHex(colors.sidebar, bg);
  const card = normalizeHex(colors.card, sidebar);
  const border = normalizeHex(colors.border, '#1e2230');
  const text = normalizeHex(colors.text, '#f1f5f9');
  const accent = normalizeHex(colors.accent, '#a78bfa');
  const accent2 = normalizeHex(colors.accentSecondary, accent);
  const light = isLightColor(bg);
  // On a dark theme "raise" means lighter; on a light theme it means darker.
  const raise = (hex: string, amt: number) => shade(hex, light ? -amt : amt);

  const textSecondary = colors.textSecondary ? normalizeHex(colors.textSecondary, text) : mix(text, bg, 0.38);
  const textMuted = colors.textMuted ? normalizeHex(colors.textMuted, text) : mix(text, bg, 0.56);
  const pill = raise(card, 0.045);
  const subcard = light ? raise(card, 0.02) : mix(card, bg, 0.35);
  const borderHover = raise(border, 0.07);
  const onAccent = isLightColor(mix(accent, accent2, 0.5)) && luminance(mix(accent, accent2, 0.5)) > 0.55 ? '#0f172a' : '#ffffff';

  return {
    '--bg-app': bg,
    '--bg-sidebar': sidebar,
    '--bg-header': rgba(sidebar, 0.92),
    '--bg-card': card,
    '--bg-card-hover': raise(card, 0.03),
    '--bg-subcard': subcard,
    '--bg-input': light ? card : mix(bg, card, 0.25),
    '--bg-pill': pill,
    '--bg-code': light ? raise(bg, 0.03) : shade(bg, -0.015),
    '--border-subtle': light ? border : mix(border, bg, 0.3),
    '--border-card': border,
    '--border-hover': borderHover,
    '--border-highlight': accent2,
    '--text-primary': text,
    '--text-secondary': textSecondary,
    '--text-muted': textMuted,
    '--text-on-accent': onAccent,
    '--accent-primary': accent,
    '--accent-secondary': accent2,
    '--accent-gradient': `linear-gradient(135deg, ${accent} 0%, ${accent2} 100%)`,
    '--accent-gradient-hover': `linear-gradient(135deg, ${shade(accent, light ? -0.06 : 0.04)} 0%, ${shade(accent2, light ? -0.06 : 0.04)} 100%)`,
    '--sidebar-brand-gradient': `linear-gradient(135deg, ${accent}, ${accent2})`,
    '--active-menu-bg': `linear-gradient(90deg, ${pill} 0%, ${sidebar} 100%)`,
    '--active-menu-border': accent2,
    '--active-menu-text': text,
    '--chat-agent-bg': subcard,
    '--chat-agent-border': borderHover,
    '--chat-agent-text': mix(text, bg, 0.1),
    '--card-shadow': light ? '0 4px 16px rgba(15, 23, 42, 0.06)' : '0 4px 20px rgba(0, 0, 0, 0.3)',
    '--modal-overlay': light ? 'rgba(15, 23, 42, 0.55)' : rgba(shade(bg, -0.03), 0.78),
    '--scrollbar-thumb': borderHover,
    '--scrollbar-track': bg,
    '--logo-on-light': light ? 'block' : 'none',
    '--logo-on-dark': light ? 'none' : 'block',
  };
}

/* ==========================================================================
   Custom theme storage
   ========================================================================== */

export function isCustomThemeId(id: string): boolean {
  return id.startsWith('custom_');
}

function sanitizeCustom(raw: unknown): ThemeDefinition | null {
  if (!raw || typeof raw !== 'object') return null;
  const r = raw as Partial<ThemeDefinition> & { colors?: Partial<ThemeColors> };
  if (typeof r.id !== 'string' || !isCustomThemeId(r.id) || !r.colors) return null;
  const c = r.colors;
  const need = ['bg', 'sidebar', 'card', 'border', 'text', 'accent', 'accentSecondary'] as const;
  if (need.some((k) => typeof c[k] !== 'string')) return null;
  const colors: ThemeColors = {
    bg: normalizeHex(c.bg as string),
    sidebar: normalizeHex(c.sidebar as string),
    card: normalizeHex(c.card as string),
    border: normalizeHex(c.border as string),
    text: normalizeHex(c.text as string),
    accent: normalizeHex(c.accent as string),
    accentSecondary: normalizeHex(c.accentSecondary as string),
  };
  if (typeof c.textSecondary === 'string') colors.textSecondary = normalizeHex(c.textSecondary);
  if (typeof c.textMuted === 'string') colors.textMuted = normalizeHex(c.textMuted);
  return {
    id: r.id,
    name: typeof r.name === 'string' && r.name.trim() ? r.name.trim().slice(0, 40) : 'Custom theme',
    category: 'custom',
    description:
      typeof r.description === 'string' && r.description.trim()
        ? r.description.trim().slice(0, 160)
        : 'Built in the Theme Builder.',
    iconName: 'Palette',
    colors,
    custom: true,
  };
}

export function loadCustomThemes(): ThemeDefinition[] {
  try {
    const raw = localStorage.getItem(CUSTOM_THEMES_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.map(sanitizeCustom).filter((t): t is ThemeDefinition => t !== null);
  } catch {
    return [];
  }
}

export function saveCustomThemes(themes: ThemeDefinition[]): void {
  try {
    localStorage.setItem(CUSTOM_THEMES_STORAGE_KEY, JSON.stringify(themes));
  } catch {
    // storage unavailable
  }
}

export function newCustomThemeId(): string {
  return `custom_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
}

/** Parse a theme pasted as JSON (the Theme Builder's export). */
export function parseThemeJson(text: string): ThemeDefinition | null {
  try {
    const raw = JSON.parse(text) as Partial<ThemeDefinition>;
    const withId = { ...raw, id: typeof raw.id === 'string' && isCustomThemeId(raw.id) ? raw.id : newCustomThemeId() };
    return sanitizeCustom(withId);
  } catch {
    return null;
  }
}

/* ==========================================================================
   Applying a theme to the document
   ========================================================================== */

export function allThemes(custom: ThemeDefinition[] = loadCustomThemes()): ThemeDefinition[] {
  return [...THEMES, ...custom];
}

export function findTheme(id: ThemeId, custom: ThemeDefinition[] = loadCustomThemes()): ThemeDefinition | undefined {
  return allThemes(custom).find((t) => t.id === id);
}

export function getStoredTheme(custom: ThemeDefinition[] = loadCustomThemes()): ThemeId {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored && findTheme(stored, custom)) {
      return stored;
    }
  } catch {
    // localStorage might be unavailable
  }
  return DEFAULT_THEME_ID;
}

/** Set every derived token inline on <html>, overriding the preset blocks in studio.css. */
export function applyColorTokens(colors: ThemeColors): void {
  const tokens = deriveTokens(colors);
  const style = document.documentElement.style;
  for (const name of THEME_TOKEN_NAMES) style.setProperty(name, tokens[name]);
}

export function clearColorTokens(): void {
  const style = document.documentElement.style;
  for (const name of THEME_TOKEN_NAMES) style.removeProperty(name);
}

/**
 * Apply a theme. Presets switch `data-theme`; custom themes set
 * `data-theme="custom"` and write their derived tokens inline. The inline
 * tokens are also cached so the pre-React script in index.html can paint a
 * custom theme before the bundle loads.
 */
export function applyTheme(id: ThemeId, def?: ThemeDefinition): void {
  try {
    const theme = def ?? findTheme(id);
    const root = document.documentElement;
    if (theme?.custom) {
      root.setAttribute('data-theme', CUSTOM_THEME_ATTR);
      applyColorTokens(theme.colors);
      localStorage.setItem(`${THEME_STORAGE_KEY}_tokens`, JSON.stringify(deriveTokens(theme.colors)));
    } else {
      clearColorTokens();
      root.setAttribute('data-theme', id);
      localStorage.removeItem(`${THEME_STORAGE_KEY}_tokens`);
    }
    localStorage.setItem(THEME_STORAGE_KEY, id);
  } catch {
    // ignore
  }
}

/** Temporarily show `colors` without storing anything; `null` restores the stored theme. */
export function previewColors(colors: ThemeColors | null, fallback: ThemeId, custom: ThemeDefinition[]): void {
  try {
    if (colors) {
      document.documentElement.setAttribute('data-theme', CUSTOM_THEME_ATTR);
      applyColorTokens(colors);
      return;
    }
    const def = findTheme(fallback, custom);
    const root = document.documentElement;
    if (def?.custom) {
      root.setAttribute('data-theme', CUSTOM_THEME_ATTR);
      applyColorTokens(def.colors);
    } else {
      clearColorTokens();
      root.setAttribute('data-theme', fallback);
    }
  } catch {
    // ignore
  }
}
