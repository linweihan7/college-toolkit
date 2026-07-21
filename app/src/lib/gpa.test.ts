import { describe, it, expect } from 'vitest';
import { gpaOf, gpaByTerm } from './gpa';
import type { Course } from './types';

const c = (id: number, name: string, term: string, credits: number, grade: Course['grade']): Course =>
  ({ id, name, term, credits, grade });

describe('gpaOf', () => {
  it('returns 0 for no courses', () => {
    expect(gpaOf([])).toEqual({ totalCredits: 0, gpa: 0 });
  });

  it('computes a credit-weighted average', () => {
    // 4cr A (4.0) + 3cr B (3.0) = (16 + 9) / 7 = 3.571...
    const r = gpaOf([c(1, 'Calc', 'F26', 4, 'A'), c(2, 'Eng', 'F26', 3, 'B')]);
    expect(r.totalCredits).toBe(7);
    expect(r.gpa).toBeCloseTo(3.5714, 3);
  });

  it('weights by credits, not course count', () => {
    const r = gpaOf([c(1, 'Big', 'F26', 5, 'A'), c(2, 'Small', 'F26', 1, 'F')]);
    expect(r.gpa).toBeCloseTo((5 * 4 + 1 * 0) / 6, 3);
  });
});

describe('gpaByTerm', () => {
  it('groups by term preserving first-seen order, each with its own GPA', () => {
    const groups = gpaByTerm([
      c(1, 'A', 'Fall 2025', 4, 'A'),
      c(2, 'B', 'Spring 2026', 3, 'B'),
      c(3, 'C', 'Fall 2025', 2, 'A'),
    ]);
    expect(groups.map((g) => g.term)).toEqual(['Fall 2025', 'Spring 2026']);
    expect(groups[0].gpa).toBe(4.0);
    expect(groups[1].gpa).toBe(3.0);
  });
});
