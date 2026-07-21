// Local-time date helpers. Everything is stored as 'YYYY-MM-DD' and parsed as a
// LOCAL date, avoiding the classic UTC off-by-one-day bug.

export function todayISO(): string {
  return isoOf(new Date());
}

export function isoOf(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function parseISODate(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
}

export function formatShortDate(iso: string): string {
  return parseISODate(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export function formatTime12h(t: string): string {
  const [h, m] = t.split(':').map(Number);
  const period = h >= 12 ? 'PM' : 'AM';
  const h12 = ((h + 11) % 12) + 1;
  return `${h12}:${String(m).padStart(2, '0')} ${period}`;
}

// Consecutive checked days ending today or yesterday.
export function currentStreak(checks: Record<string, boolean>): number {
  if (!checks) return 0;
  let streak = 0;
  const cursor = new Date();
  if (!checks[isoOf(cursor)]) cursor.setDate(cursor.getDate() - 1);
  while (checks[isoOf(cursor)]) {
    streak++;
    cursor.setDate(cursor.getDate() - 1);
  }
  return streak;
}
