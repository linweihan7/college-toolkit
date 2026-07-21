import { describe, it, expect } from 'vitest';
import { parseNaturalDate, parseNaturalTime, heuristicParse } from './nlp';
import type { Course, Habit } from './types';

// Fixed reference date: Friday, 2026-07-17
const NOW = new Date(2026, 6, 17, 9, 0, 0);

describe('parseNaturalDate', () => {
  it('resolves today and tomorrow', () => {
    expect(parseNaturalDate('due today', NOW)?.date).toBe('2026-07-17');
    expect(parseNaturalDate('due tomorrow', NOW)?.date).toBe('2026-07-18');
  });

  it('a bare weekday means the upcoming one (next thursday)', () => {
    // From Fri Jul 17, next Thursday is Jul 23
    expect(parseNaturalDate('next thursday', NOW)?.date).toBe('2026-07-23');
    expect(parseNaturalDate('thursday', NOW)?.date).toBe('2026-07-23');
  });

  it('rolls M/D into next year when already past', () => {
    expect(parseNaturalDate('1/5', NOW)?.date).toBe('2027-01-05');
    expect(parseNaturalDate('8/1', NOW)?.date).toBe('2026-08-01');
  });

  it('parses month-name dates', () => {
    expect(parseNaturalDate('dec 3', NOW)?.date).toBe('2026-12-03');
  });

  it('returns null when there is no date', () => {
    expect(parseNaturalDate('buy milk', NOW)).toBeNull();
  });
});

describe('parseNaturalTime', () => {
  it('parses 12h and 24h forms', () => {
    expect(parseNaturalTime('2pm')?.time).toBe('14:00');
    expect(parseNaturalTime('9:30am')?.time).toBe('09:30');
    expect(parseNaturalTime('12am')?.time).toBe('00:00');
    expect(parseNaturalTime('noon 12pm')?.time).toBe('12:00');
  });

  it('returns null without a time', () => {
    expect(parseNaturalTime('essay')).toBeNull();
  });
});

describe('heuristicParse', () => {
  const courses: Course[] = [{ id: 1, name: 'Econ 101', term: 'F26', credits: 3, grade: 'A' }];
  const habits: Habit[] = [{ id: 5, name: 'Gym', checks: {} }];

  it('"coffee 6.50" -> food expense', () => {
    const r = heuristicParse('coffee 6.50', courses, habits, NOW);
    expect(r.type).toBe('expense');
    expect(r.fields.amount).toBe(6.5);
    expect(r.fields.category).toBe('food');
  });

  it('"econ midterm next thursday 2pm" -> assignment on the right course', () => {
    const r = heuristicParse('econ midterm next thursday 2pm', courses, habits, NOW);
    expect(r.type).toBe('assignment');
    expect(r.fields.courseId).toBe(1);
    expect(r.fields.dueDate).toBe('2026-07-23');
    expect(r.fields.dueTime).toBe('14:00');
  });

  it('"gym streak done" -> habit check', () => {
    const r = heuristicParse('gym streak done', courses, habits, NOW);
    expect(r.type).toBe('habit');
    expect(r.fields.habitId).toBe(5);
  });

  it('vague text -> low-confidence todo', () => {
    const r = heuristicParse('stuff for later maybe', courses, habits, NOW);
    expect(r.type).toBe('todo');
    expect(r.confidence).toBeLessThan(0.6);
  });
});
