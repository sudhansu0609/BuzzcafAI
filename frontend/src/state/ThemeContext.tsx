import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  THEMES,
  applyTheme,
  getStoredTheme,
  type ThemeDefinition,
  type ThemeId,
} from '../lib/theme';

interface ThemeContextValue {
  theme: ThemeId;
  themeDef: ThemeDefinition;
  setTheme: (id: ThemeId) => void;
  themes: ThemeDefinition[];
  cycleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeId>(() => getStoredTheme());

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  const setTheme = (id: ThemeId) => {
    setThemeState(id);
    applyTheme(id);
  };

  const cycleTheme = () => {
    const currentIndex = THEMES.findIndex((t) => t.id === theme);
    const nextIndex = (currentIndex + 1) % THEMES.length;
    setTheme(THEMES[nextIndex].id);
  };

  const themeDef = useMemo(() => {
    return THEMES.find((t) => t.id === theme) || THEMES[0];
  }, [theme]);

  const value = useMemo(
    () => ({
      theme,
      themeDef,
      setTheme,
      themes: THEMES,
      cycleTheme,
    }),
    [theme, themeDef],
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
