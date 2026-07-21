import { useEffect, useState, type ComponentType } from 'react';
import { useTheme } from './state/useTheme';
import { Dashboard } from './components/Dashboard';
import { Expenses } from './components/Expenses';
import { Todo } from './components/Todo';
import { Gpa } from './components/Gpa';
import { Habits } from './components/Habits';
import { Placeholder } from './components/Placeholder';

interface Tab {
  id: string;
  label: string;
  icon: string;
  Component: ComponentType;
}

// One component per feature tab. Ported tabs use their real component; the rest
// render a Placeholder until their migration increment lands.
const TABS: Tab[] = [
  { id: 'dashboard', label: 'Dashboard', icon: '🏠', Component: Dashboard },
  { id: 'expenses', label: 'Expenses', icon: '💰', Component: Expenses },
  { id: 'todo', label: 'To-Do', icon: '✅', Component: Todo },
  { id: 'gpa', label: 'GPA', icon: '🎯', Component: Gpa },
  { id: 'habits', label: 'Habits', icon: '🔥', Component: Habits },
  { id: 'schedule', label: 'Schedule', icon: '📅', Component: () => <Placeholder name="Class Schedule" /> },
  { id: 'assignments', label: 'Assignments', icon: '📝', Component: () => <Placeholder name="Assignments" /> },
  { id: 'timer', label: 'Timer', icon: '⏱️', Component: () => <Placeholder name="Study Timer" /> },
  { id: 'insights', label: 'Insights', icon: '📈', Component: () => <Placeholder name="Insights" /> },
  { id: 'wellness', label: 'Wellness', icon: '💚', Component: () => <Placeholder name="Wellness" /> },
  { id: 'contacts', label: 'Contacts', icon: '👤', Component: () => <Placeholder name="Contacts" /> },
  { id: 'guide', label: 'Guide', icon: '🧭', Component: () => <Placeholder name="Survival Guide" /> },
  { id: 'weather', label: 'Weather', icon: '🌤️', Component: () => <Placeholder name="Weather" /> },
];

export function App() {
  const [, toggleTheme] = useTheme();
  const [active, setActive] = useState<string>(() => location.hash.slice(1) || 'dashboard');

  useEffect(() => {
    const onHash = () => setActive(location.hash.slice(1) || 'dashboard');
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  function go(id: string) {
    setActive(id);
    history.replaceState(null, '', `#${id}`);
  }

  const current = TABS.find((t) => t.id === active) ?? TABS[0];
  const Active = current.Component;

  return (
    <div className="app">
      <nav className="sidebar">
        <div className="brand">🎓 College Toolkit</div>
        <div className="nav-group">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`nav-btn${t.id === current.id ? ' active' : ''}`}
              onClick={() => go(t.id)}
            >
              <span aria-hidden>{t.icon}</span>
              <span>{t.label}</span>
            </button>
          ))}
        </div>
        <div className="sidebar-footer">
          <button className="theme-toggle" onClick={toggleTheme} aria-label="Toggle dark mode">◐</button>
          <span className="autosave-note">🔒 Auto-saved</span>
        </div>
      </nav>
      <main className="content">
        <div className="content-inner">
          <Active />
        </div>
      </main>
    </div>
  );
}
