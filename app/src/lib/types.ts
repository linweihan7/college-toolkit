// One source of truth for every persisted shape. Keys are namespaced the same
// way the original app used them, so an existing user's localStorage carries over.

export type ExpenseCategory = 'food' | 'transport' | 'fun' | 'other';

export interface Expense {
  id: number;
  name: string;
  amount: number;
  category: ExpenseCategory;
  date: string; // YYYY-MM-DD
}

export type Priority = 'high' | 'medium' | 'low';

export interface Todo {
  id: number;
  text: string;
  done: boolean;
  dueDate: string | null;
  priority: Priority;
}

export interface Course {
  id: number;
  name: string;
  term: string;
  credits: number;
  grade: Grade;
}

export type Grade = 'A' | 'A-' | 'B+' | 'B' | 'B-' | 'C+' | 'C' | 'C-' | 'D+' | 'D' | 'F';

export interface Habit {
  id: number;
  name: string;
  checks: Record<string, boolean>; // { 'YYYY-MM-DD': true }
}

export interface Assignment {
  id: number;
  courseId: number | null;
  courseName?: string;
  title: string;
  dueDate: string | null;
  dueTime?: string | null;
  pointsPossible: number | null;
  pointsEarned: number | null;
  canvas?: boolean;
  canvasUid?: string;
}

// The registry of every synced/backed-up localStorage key and the type it holds.
export interface DataShape {
  'college-toolkit:expenses': Expense[];
  'college-toolkit:todos': Todo[];
  'college-toolkit:gpa': Course[];
  'college-toolkit:habits': Habit[];
  'college-toolkit:assignments': Assignment[];
  'college-toolkit:theme': 'light' | 'dark';
}

export type DataKey = keyof DataShape;

export const DATA_KEYS: DataKey[] = [
  'college-toolkit:expenses',
  'college-toolkit:todos',
  'college-toolkit:gpa',
  'college-toolkit:habits',
  'college-toolkit:assignments',
  'college-toolkit:theme',
];

export const GRADE_POINTS: Record<Grade, number> = {
  A: 4.0, 'A-': 3.7, 'B+': 3.3, B: 3.0, 'B-': 2.7,
  'C+': 2.3, C: 2.0, 'C-': 1.7, 'D+': 1.3, D: 1.0, F: 0.0,
};
