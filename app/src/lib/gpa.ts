import type { Course } from './types';
import { GRADE_POINTS } from './types';

export interface GpaResult {
  totalCredits: number;
  gpa: number;
}

// Credit-weighted GPA. Empty list yields 0 credits / 0.0 GPA.
export function gpaOf(courses: Course[]): GpaResult {
  const totalCredits = courses.reduce((s, c) => s + c.credits, 0);
  const totalPoints = courses.reduce((s, c) => s + c.credits * GRADE_POINTS[c.grade], 0);
  return { totalCredits, gpa: totalCredits > 0 ? totalPoints / totalCredits : 0 };
}

// Preserves first-seen order of terms, each with its own GPA.
export function gpaByTerm(courses: Course[]): { term: string; courses: Course[]; gpa: number }[] {
  const order: string[] = [];
  courses.forEach((c) => {
    const t = c.term || 'General';
    if (!order.includes(t)) order.push(t);
  });
  return order.map((term) => {
    const termCourses = courses.filter((c) => (c.term || 'General') === term);
    return { term, courses: termCourses, gpa: gpaOf(termCourses).gpa };
  });
}
