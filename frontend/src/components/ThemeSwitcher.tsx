import { useEffect, useRef, useState } from 'react';
import {
  Check,
  ChevronDown,
  Coffee,
  Feather,
  Layers,
  Moon,
  Sun,
  Sunset,
  Zap,
  Sparkles,
  Leaf,
} from 'lucide-react';
import { useTheme } from '../state/ThemeContext';
import type { ThemeDefinition } from '../lib/theme';

export function getThemeIcon(iconName: ThemeDefinition['iconName'], size = 16) {
  switch (iconName) {
    case 'Sun':
      return <Sun size={size} />;
    case 'Feather':
      return <Feather size={size} />;
    case 'Layers':
      return <Layers size={size} />;
    case 'Coffee':
      return <Coffee size={size} />;
    case 'Zap':
      return <Zap size={size} />;
    case 'Sunset':
      return <Sunset size={size} />;
    case 'Sparkles':
      return <Sparkles size={size} />;
    case 'Leaf':
      return <Leaf size={size} />;
    case 'Moon':
    default:
      return <Moon size={size} />;
  }
}

export function ThemeSwitcher() {
  const { theme, themeDef, setTheme, themes } = useTheme();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false);
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('keydown', handleKeyDown);
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open]);

  return (
    <div className="theme-dropdown-container" ref={containerRef}>
      <button
        type="button"
        className="theme-switcher-btn"
        onClick={() => setOpen((prev) => !prev)}
        aria-haspopup="true"
        aria-expanded={open}
        title="Change theme"
      >
        <span style={{ display: 'flex', alignItems: 'center', color: themeDef.colors.accent }}>
          {getThemeIcon(themeDef.iconName, 15)}
        </span>
        <span>{themeDef.name}</span>
        <div className="theme-palette-dots">
          <span className="theme-dot" style={{ backgroundColor: themeDef.colors.bg, border: '1px solid var(--border-card)' }} />
          <span className="theme-dot" style={{ backgroundColor: themeDef.colors.accent }} />
          <span className="theme-dot" style={{ backgroundColor: themeDef.colors.accentSecondary }} />
        </div>
        <ChevronDown size={14} style={{ opacity: 0.7, transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
      </button>

      {open && (
        <div className="theme-dropdown-menu" role="menu">
          <div className="theme-dropdown-header">Select Theme ({themes.length})</div>
          {themes.map((t) => {
            const isActive = t.id === theme;
            return (
              <button
                key={t.id}
                type="button"
                className={`theme-option-item ${isActive ? 'active' : ''}`}
                onClick={() => {
                  setTheme(t.id);
                  setOpen(false);
                }}
                role="menuitem"
              >
                <div className="theme-option-left">
                  <span style={{ display: 'flex', alignItems: 'center', color: t.colors.accent }}>
                    {getThemeIcon(t.iconName, 15)}
                  </span>
                  <div>
                    <div className="theme-option-name" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span>{t.name}</span>
                      <span className="theme-category-badge">{t.category}</span>
                    </div>
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div className="theme-palette-dots">
                    <span className="theme-dot" style={{ backgroundColor: t.colors.bg, border: '1px solid var(--border-card)' }} />
                    <span className="theme-dot" style={{ backgroundColor: t.colors.accent }} />
                    <span className="theme-dot" style={{ backgroundColor: t.colors.accentSecondary }} />
                  </div>
                  {isActive && <Check size={14} style={{ color: 'var(--border-highlight)' }} />}
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
