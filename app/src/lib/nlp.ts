// Pure natural-language quick-capture parser. Given a note plus the user's
// courses and habits, decide which tab it belongs in and pre-fill fields.
// No DOM, no storage — fully unit-testable.

import type { Course, ExpenseCategory, Habit, Priority } from './types';
import { isoOf, todayISO } from './dates';

const WEEKDAY_MAP: Record<string, number> = {
  sun: 0, sunday: 0, mon: 1, monday: 1, tue: 2, tues: 2, tuesday: 2,
  wed: 3, wednesday: 3, thu: 4, thur: 4, thurs: 4, thursday: 4,
  fri: 5, friday: 5, sat: 6, saturday: 6,
};
const MONTH_MAP: Record<string, number> = {
  jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5,
  jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11,
};

export interface DateHit { date: string; matched: string; }
export interface TimeHit { time: string; matched: string; }

export function parseNaturalDate(lower: string, now = new Date()): DateHit | null {
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  if (/(^|\s)(today|tonight)(\s|$)/.test(lower)) return { date: isoOf(now), matched: /tonight/.test(lower) ? 'tonight' : 'today' };
  if (/(^|\s)tomorrow(\s|$)/.test(lower)) { const d = new Date(now); d.setDate(d.getDate() + 1); return { date: isoOf(d), matched: 'tomorrow' }; }

  let m = lower.match(/\b(next\s+)?(sunday|monday|tuesday|wednesday|thursday|friday|saturday|sun|mon|tues|tue|wed|thurs|thur|thu|fri|sat)\b/);
  if (m) {
    const d = new Date(now);
    let diff = (WEEKDAY_MAP[m[2]] - d.getDay() + 7) % 7;
    if (diff === 0) diff = 7;
    d.setDate(d.getDate() + diff);
    return { date: isoOf(d), matched: m[0] };
  }
  m = lower.match(/\b(\d{1,2})\/(\d{1,2})\b/);
  if (m) {
    const d = new Date(now.getFullYear(), +m[1] - 1, +m[2]);
    if (d < startOfToday) d.setFullYear(d.getFullYear() + 1);
    return { date: isoOf(d), matched: m[0] };
  }
  m = lower.match(/\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})\b/);
  if (m) {
    const d = new Date(now.getFullYear(), MONTH_MAP[m[1]], +m[2]);
    if (d < startOfToday) d.setFullYear(d.getFullYear() + 1);
    return { date: isoOf(d), matched: m[0] };
  }
  return null;
}

export function parseNaturalTime(lower: string): TimeHit | null {
  let m = lower.match(/\b(\d{1,2}):(\d{2})\s*(am|pm)?\b/);
  if (!m) {
    const m2 = lower.match(/\b(\d{1,2})\s*(am|pm)\b/);
    if (m2) m = [m2[0], m2[1], '00', m2[2]] as unknown as RegExpMatchArray;
  }
  if (!m) return null;
  let h = +m[1];
  const min = +m[2];
  if (m[3] === 'pm' && h < 12) h += 12;
  if (m[3] === 'am' && h === 12) h = 0;
  if (h > 23 || min > 59) return null;
  return { time: `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`, matched: m[0] };
}

export type CaptureType = 'expense' | 'todo' | 'assignment' | 'habit';

export interface ParseResult {
  type: CaptureType;
  confidence: number;
  fields: Record<string, unknown>;
}

export function guessCategory(name: string): ExpenseCategory {
  if (/coffee|boba|lunch|dinner|breakfast|food|pizza|snack|grocer|restaurant/i.test(name)) return 'food';
  if (/bus|uber|lyft|gas|train|parking|flight/i.test(name)) return 'transport';
  if (/movie|game|concert|party|ticket/i.test(name)) return 'fun';
  return 'other';
}

export function heuristicParse(raw: string, courses: Course[], habits: Habit[], now = new Date()): ParseResult {
  const text = raw.trim().replace(/\s+/g, ' ');
  const lower = text.toLowerCase();

  const habitHit = habits.find((h) => lower.includes(h.name.toLowerCase()));
  if (habitHit && /\b(done|did|check(ed)?|complete(d)?|streak)\b/.test(lower)) {
    return { type: 'habit', confidence: 0.9, fields: { habitId: habitHit.id } };
  }

  const dateHit = parseNaturalDate(lower, now);
  const timeHit = parseNaturalTime(lower);

  const amountMatch = text.match(/^(.+?)\s+\$?(\d+(?:\.\d{1,2})?)\s*$/);
  if (amountMatch && !dateHit && !timeHit) {
    const name = amountMatch[1].trim();
    return {
      type: 'expense',
      confidence: text.includes('$') ? 0.9 : 0.75,
      fields: { name, amount: parseFloat(amountMatch[2]), category: guessCategory(name), date: todayISO() },
    };
  }

  let title = text;
  if (dateHit) title = title.replace(dateHit.matched, ' ');
  if (timeHit) title = title.replace(timeHit.matched, ' ');
  title = title.replace(/\b(due|by|on|at|next)\b/gi, ' ').replace(/\s+/g, ' ').trim();
  if (!title) title = text;

  const courseHit = courses.find((c) =>
    c.name.toLowerCase().split(/[^a-z0-9]+/).some((w) => w.length > 2 && lower.includes(w))
  );
  const looksAcademic = /\b(midterm|final|exam|quiz|essay|paper|homework|hw|assignment|project|lab|reading|chapter)\b/i.test(lower);

  if (courseHit && looksAcademic) {
    return {
      type: 'assignment',
      confidence: dateHit ? 0.8 : 0.65,
      fields: { title, courseId: courseHit.id, dueDate: dateHit?.date ?? null, dueTime: timeHit?.time ?? null, pointsPossible: 100 },
    };
  }

  const priority: Priority = 'medium';
  return {
    type: 'todo',
    confidence: dateHit ? 0.75 : 0.45,
    fields: { text: title, dueDate: dateHit?.date ?? null, priority },
  };
}
