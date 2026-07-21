import { useMemo, useState } from 'react';
import { useStore } from '../state/useStore';
import type { Habit } from '../lib/types';
import { currentStreak, isoOf, todayISO } from '../lib/dates';

const DAY_LETTERS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

function mondayOf(d: Date): Date {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
  return x;
}

export function Habits() {
  const [habits, setHabits] = useStore('college-toolkit:habits', [] as Habit[]);
  const [name, setName] = useState('');
  const [weekStart, setWeekStart] = useState<Date>(() => mondayOf(new Date()));

  const nextId = useMemo(() => habits.reduce((m, h) => Math.max(m, h.id), 0) + 1, [habits]);

  const weekDates = useMemo(() => {
    return Array.from({ length: 7 }, (_, i) => {
      const d = new Date(weekStart);
      d.setDate(d.getDate() + i);
      return d;
    });
  }, [weekStart]);

  function add() {
    if (!name.trim()) return;
    setHabits([...habits, { id: nextId, name: name.trim(), checks: {} }]);
    setName('');
  }
  function remove(id: number) {
    setHabits(habits.filter((h) => h.id !== id));
  }
  function toggle(id: number, iso: string) {
    setHabits(habits.map((h) => {
      if (h.id !== id) return h;
      const checks = { ...h.checks };
      if (checks[iso]) delete checks[iso]; else checks[iso] = true;
      return { ...h, checks };
    }));
  }

  const todayIso = todayISO();
  const rangeLabel = `${weekDates[0].toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} – ${weekDates[6].toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`;

  function shiftWeek(days: number) {
    const d = new Date(weekStart);
    d.setDate(d.getDate() + days);
    setWeekStart(d);
  }

  return (
    <div className="card">
      <h1 className="page-title">Habit Tracker</h1>
      <p className="page-sub">Check off your habits day by day.</p>

      <div className="field-row">
        <input className="field-full" placeholder="New habit (e.g. Drink water)" value={name}
          onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
        <button className="btn field-full" onClick={add}>Add Habit</button>
      </div>

      <div className="field-row" style={{ alignItems: 'center', justifyContent: 'space-between' }}>
        <button className="btn-secondary btn" onClick={() => shiftWeek(-7)} aria-label="Previous week">‹</button>
        <strong style={{ fontSize: 14 }}>{rangeLabel}</strong>
        <button className="btn-secondary btn" onClick={() => shiftWeek(7)} aria-label="Next week">›</button>
      </div>

      <div className="habit-grid-header">
        <span />
        {weekDates.map((d, i) => (
          <span key={i} style={isoOf(d) === todayIso ? { color: 'var(--accent)' } : undefined}>{DAY_LETTERS[i]}</span>
        ))}
        <span />
      </div>

      {habits.length === 0 && <div className="empty-state">Add a habit to start tracking</div>}
      {habits.map((h) => {
        const streak = currentStreak(h.checks);
        return (
          <div key={h.id} className="habit-row">
            <span className="habit-name">
              {h.name}{streak > 0 && <span style={{ color: 'var(--ember)', fontSize: 10, fontWeight: 700, marginLeft: 3 }}> 🔥{streak}</span>}
            </span>
            {weekDates.map((d, i) => {
              const iso = isoOf(d);
              return (
                <button key={i} className={`habit-check${h.checks[iso] ? ' checked' : ''}`}
                  onClick={() => toggle(h.id, iso)} aria-label={`${h.name} on ${iso}`} />
              );
            })}
            <button className="icon-btn" onClick={() => remove(h.id)} aria-label={`Delete ${h.name}`}>🗑</button>
          </div>
        );
      })}
    </div>
  );
}
