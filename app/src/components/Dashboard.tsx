import { useStore } from '../state/useStore';
import type { Assignment, Course, Expense, Habit, Todo } from '../lib/types';
import { currentStreak, parseISODate, todayISO } from '../lib/dates';
import { gpaOf } from '../lib/gpa';

export function Dashboard() {
  const [expenses] = useStore('college-toolkit:expenses', [] as Expense[]);
  const [todos] = useStore('college-toolkit:todos', [] as Todo[]);
  const [courses] = useStore('college-toolkit:gpa', [] as Course[]);
  const [habits] = useStore('college-toolkit:habits', [] as Habit[]);
  const [assignments] = useStore('college-toolkit:assignments', [] as Assignment[]);

  const todayIso = todayISO();
  const monthKey = todayIso.slice(0, 7);
  const monthSpend = expenses.filter((e) => e.date.slice(0, 7) === monthKey).reduce((s, e) => s + e.amount, 0);
  const activeTasks = todos.filter((t) => !t.done);
  const overdue = activeTasks.filter((t) => t.dueDate && t.dueDate < todayIso).length;
  const { totalCredits, gpa } = gpaOf(courses);
  const bestStreak = habits.reduce((m, h) => Math.max(m, currentStreak(h.checks || {})), 0);

  const upcoming = assignments
    .filter((a) => a.pointsEarned === null && a.dueDate)
    .sort((a, b) => (a.dueDate! < b.dueDate! ? -1 : 1))[0];
  let nextDueCaption = 'All caught up';
  if (upcoming?.dueDate) {
    const days = Math.round((parseISODate(upcoming.dueDate).getTime() - parseISODate(todayIso).getTime()) / 86400000);
    nextDueCaption = days <= 0 ? 'Due today' : days === 1 ? 'Due tomorrow' : `Due in ${days} days`;
  }

  const cards = [
    { icon: '💰', label: 'This Month', value: '$' + monthSpend.toFixed(2), caption: 'spent' },
    { icon: '✅', label: 'Tasks', value: String(activeTasks.length), caption: overdue ? `${overdue} overdue` : 'active' },
    { icon: '🎯', label: 'GPA', value: totalCredits ? gpa.toFixed(2) : '—', caption: totalCredits ? `${totalCredits} credits` : 'No courses' },
    { icon: '🔥', label: 'Best Streak', value: String(bestStreak), caption: bestStreak === 1 ? 'day' : 'days' },
    { icon: '📝', label: 'Next Due', value: upcoming ? upcoming.title : '—', caption: nextDueCaption },
    { icon: '📈', label: 'Tracked', value: String(expenses.length + todos.length + courses.length), caption: 'items total' },
  ];

  return (
    <>
      <div className="card">
        <h1 className="page-title">Dashboard</h1>
        <p className="page-sub">Your college life at a glance.</p>
      </div>
      <div className="stat-grid">
        {cards.map((c) => (
          <div className="stat-card" key={c.label}>
            <div style={{ fontSize: 17 }}>{c.icon}</div>
            <div className="stat-label">{c.label}</div>
            <div className="stat-value" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{c.value}</div>
            <div className="stat-caption">{c.caption}</div>
          </div>
        ))}
      </div>
    </>
  );
}
