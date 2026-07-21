import { useCallback, useEffect, useState } from 'react';

const KEY = 'college-toolkit:theme';

type Theme = 'light' | 'dark';

function systemPrefersDark(): boolean {
  return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
}

// Theme is applied to <html data-theme>. A saved choice wins; otherwise we follow
// the OS. Kept out of the synced DataShape so a phone in dark mode doesn't force
// a laptop to match.
export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = localStorage.getItem(KEY);
    if (saved === 'dark' || saved === 'light') return saved;
    return systemPrefersDark() ? 'dark' : 'light';
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((prev) => {
      const next: Theme = prev === 'dark' ? 'light' : 'dark';
      localStorage.setItem(KEY, next);
      return next;
    });
  }, []);

  return [theme, toggle];
}
