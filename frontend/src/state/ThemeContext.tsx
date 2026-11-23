import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  THEMES,
  applyTheme,
  getStoredTheme,
  loadCustomThemes,
  previewColors,
  saveCustomThemes,
  type ThemeColors,
  type ThemeDefinition,
  type ThemeId,
} from '../lib/theme';

interface ThemeContextValue {
  theme: ThemeId;
  themeDef: ThemeDefinition;
  setTheme: (id: ThemeId) => void;
  /** Presets followed by the user's custom themes. */
  themes: ThemeDefinition[];
  customThemes: ThemeDefinition[];
  cycleTheme: () => void;
  /** Add or replace a custom theme (matched by id) and make it active. */
  saveCustomTheme: (def: ThemeDefinition) => void;
  deleteCustomTheme: (id: ThemeId) => void;
  /** Live-preview a colour set without saving; `null` ends the preview. */
  preview: (colors: ThemeColors | null) => void;
  previewing: boolean;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [customThemes, setCustomThemes] = useState<ThemeDefinition[]>(() => loadCustomThemes());
  const [theme, setThemeState] = useState<ThemeId>(() => getStoredTheme(loadCustomThemes()));
  const [previewing, setPreviewing] = useState(false);
  const customRef = useRef(customThemes);
  customRef.current = customThemes;

  const themes = useMemo(() => [...THEMES, ...customThemes], [customThemes]);

  const themeDef = useMemo(() => {
    return themes.find((t) => t.id === theme) || THEMES[0];
  }, [themes, theme]);

  useEffect(() => {
    if (!previewing) applyTheme(theme, themeDef);
  }, [theme, themeDef, previewing]);

  const setTheme = useCallback((id: ThemeId) => {
    setPreviewing(false);
    setThemeState(id);
  }, []);

  const cycleTheme = useCallback(() => {
    const currentIndex = themes.findIndex((t) => t.id === theme);
    const nextIndex = (currentIndex + 1) % themes.length;
    setTheme(themes[nextIndex].id);
  }, [themes, theme, setTheme]);

  const saveCustomTheme = useCallback(
    (def: ThemeDefinition) => {
      const next = customRef.current.some((t) => t.id === def.id)
        ? customRef.current.map((t) => (t.id === def.id ? def : t))
        : [...customRef.current, def];
      saveCustomThemes(next);
      setCustomThemes(next);
      setPreviewing(false);
      setThemeState(def.id);
      applyTheme(def.id, def);
    },
    [],
  );

  const deleteCustomTheme = useCallback(
    (id: ThemeId) => {
      const next = customRef.current.filter((t) => t.id !== id);
      saveCustomThemes(next);
      setCustomThemes(next);
      if (theme === id) setTheme(THEMES[0].id);
    },
    [theme, setTheme],
  );

  const preview = useCallback(
    (colors: ThemeColors | null) => {
      setPreviewing(colors !== null);
      previewColors(colors, theme, customRef.current);
    },
    [theme],
  );

  const value = useMemo(
    () => ({
      theme,
      themeDef,
      setTheme,
      themes,
      customThemes,
      cycleTheme,
      saveCustomTheme,
      deleteCustomTheme,
      preview,
      previewing,
    }),
    [theme, themeDef, setTheme, themes, customThemes, cycleTheme, saveCustomTheme, deleteCustomTheme, preview, previewing],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error('useTheme must be used within a ThemeProvider');
  }
  return ctx;
}
