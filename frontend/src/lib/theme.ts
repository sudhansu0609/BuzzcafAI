export type ThemeId =
  | 'dark'
  | 'light'
  | 'nordic'
  | 'slate'
  | 'espresso'
  | 'cyberpunk'
  | 'sunset'
  | 'solarized_green'
  | 'mint_light';

export type ThemeCategory = 'dark' | 'light' | 'semi-dark' | 'minimalist' | 'funky';

export interface ThemeColors {
  bg: string;
  sidebar: string;
  card: string;
  border: string;
  text: string;
  accent: string;
  accentSecondary: string;
}

export interface ThemeDefinition {
  id: ThemeId;
  name: string;
  category: ThemeCategory;
  description: string;
  iconName: 'Moon' | 'Sun' | 'Feather' | 'Layers' | 'Coffee' | 'Zap' | 'Sunset' | 'Sparkles' | 'Leaf';
  colors: ThemeColors;
}

export const THEME_STORAGE_KEY = 'buzzcaf_studio_theme';
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

export function getStoredTheme(): ThemeId {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY) as ThemeId;
    if (stored && THEMES.some((t) => t.id === stored)) {
      return stored;
    }
  } catch {
    // localStorage might be unavailable
  }
  return DEFAULT_THEME_ID;
}

export function applyTheme(id: ThemeId): void {
  try {
    document.documentElement.setAttribute('data-theme', id);
    localStorage.setItem(THEME_STORAGE_KEY, id);
  } catch {
    // ignore
  }
}
