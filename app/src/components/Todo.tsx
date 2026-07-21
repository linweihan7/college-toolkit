import { useMemo, useState } from 'react';
import { useStore } from '../state/useStore';
import type { Priority, Todo as TodoItem } from '../lib/types';
import { formatShortDate, todayISO } from '../lib/dates';

const PRIORITIES: Record<Priority, { label: string; color: string }> = {
  high: { label: 'High', color: '#d43f3f' },
  medium: { label: 'Medium', color: '#5546e0' },
  low: { label: 'Low', color: '#4d96ff' },
};
const ORDER: Record<Priority, number> = { high: 0, medium: 1, low: 2 };
type Filter = 'all' | 'active' | 'completed';

export function Todo() {
  const [todos, setTodos] = useStore('college-toolkit:todos', [] as TodoItem[]);
  const [text, setText] = useState('');
  const [due, setDue] = useState('');
  const [priority, setPriority] = useState<Priority>('medium');
  const [filter, setFilter] = useState<Filter>('all');

  const nextId = useMemo(() => todos.reduce((m, t) => Math.max(m, t.id), 0) + 1, [todos]);

  function add() {
    if (!text.trim()) return;
    setTodos([...todos, { id: nextId, text: text.trim(), done: false, dueDate: due || null, priority }]);
    setText('');
    setDue('');
  }
  function toggle(id: number) {
    setTodos(todos.map((t) => (t.id === id ? { ...t, done: !t.done } : t)));
  }
  function remove(id: number) {
    setTodos(todos.filter((t) => t.id !== id));
  }

  const visible = todos
    .filter((t) => (filter === 'active' ? !t.done : filter === 'completed' ? t.done : true))
    .sort((a, b) => {
      if (a.done !== b.done) return a.done ? 1 : -1;
      const d = (a.dueDate || '9999').localeCompare(b.dueDate || '9999');
      return d !== 0 ? d : ORDER[a.priority] - ORDER[b.priority];
    });
  const remaining = todos.filter((t) => !t.done).length;

  return (
    <div className="card">
      <h1 className="page-title">To-Do List</h1>
      <p className="page-sub">Assignments and errands.</p>

      <div className="field-row">
        <input className="field-full" placeholder="Task name" value={text}
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
        <input className="field-half" type="date" value={due} onChange={(e) => setDue(e.target.value)} />
        <select className="field-half" value={priority} onChange={(e) => setPriority(e.target.value as Priority)}>
          {(Object.keys(PRIORITIES) as Priority[]).map((p) => <option key={p} value={p}>{PRIORITIES[p].label}</option>)}
        </select>
        <button className="btn field-full" onClick={add}>Add</button>
      </div>

      <div className="field-row" style={{ marginBottom: 12 }}>
        {(['all', 'active', 'completed'] as Filter[]).map((f) => (
          <button key={f} className={`btn ${filter === f ? '' : 'btn-secondary'}`}
            style={{ flex: 1, fontSize: 12, padding: '6px 12px' }} onClick={() => setFilter(f)}>
            {f[0].toUpperCase() + f.slice(1)}
          </button>
        ))}
      </div>

      <ul className="list">
        {visible.length === 0 && <li className="empty-state">Nothing here</li>}
        {visible.map((t) => {
          const overdue = t.dueDate && !t.done && t.dueDate < todayISO();
          const p = PRIORITIES[t.priority];
          return (
            <li key={t.id}>
              <span className="row-info">
                <input type="checkbox" checked={t.done} onChange={() => toggle(t.id)}
                  style={{ width: 18, height: 18, flexShrink: 0 }} />
                <span className="pill" style={{ background: p.color + '22', color: p.color }}>{p.label}</span>
                <span className="row-details">
                  <span className="row-name" style={t.done ? { textDecoration: 'line-through', color: 'var(--muted)' } : undefined}>{t.text}</span>
                  {t.dueDate && (
                    <span className="row-meta" style={overdue ? { color: 'var(--bad)', fontWeight: 600 } : undefined}>
                      {overdue ? 'Overdue · ' : ''}{formatShortDate(t.dueDate)}
                    </span>
                  )}
                </span>
              </span>
              <button className="icon-btn" onClick={() => remove(t.id)} aria-label={`Delete ${t.text}`}>🗑</button>
            </li>
          );
        })}
      </ul>

      <div className="total-row" style={{ fontSize: 12, fontWeight: 600, color: 'var(--muted)', justifyContent: 'center' }}>
        {remaining} of {todos.length} remaining
      </div>
    </div>
  );
}
