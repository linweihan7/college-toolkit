import { useMemo, useState } from 'react';
import { useStore } from '../state/useStore';
import type { Course, Grade } from '../lib/types';
import { GRADE_POINTS } from '../lib/types';
import { gpaByTerm, gpaOf } from '../lib/gpa';

const GRADES = Object.keys(GRADE_POINTS) as Grade[];

export function Gpa() {
  const [courses, setCourses] = useStore('college-toolkit:gpa', [] as Course[]);
  const [name, setName] = useState('');
  const [term, setTerm] = useState('');
  const [credits, setCredits] = useState('');
  const [grade, setGrade] = useState<Grade>('A');

  const nextId = useMemo(() => courses.reduce((m, c) => Math.max(m, c.id), 0) + 1, [courses]);

  function add() {
    const cr = parseFloat(credits);
    if (!name.trim() || isNaN(cr) || cr <= 0) return;
    setCourses([...courses, { id: nextId, name: name.trim(), term: term.trim() || 'General', credits: cr, grade }]);
    setName('');
    setTerm('');
    setCredits('');
  }
  function remove(id: number) {
    setCourses(courses.filter((c) => c.id !== id));
  }

  const groups = gpaByTerm(courses);
  const { totalCredits, gpa } = gpaOf(courses);

  return (
    <div className="card">
      <h1 className="page-title">GPA Calculator</h1>
      <p className="page-sub">Grouped by term, with a cumulative GPA.</p>

      <div className="field-row">
        <input className="field-full" placeholder="Course name" value={name}
          onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
        <input className="field-full" placeholder="Term (e.g. Fall 2026)" value={term} onChange={(e) => setTerm(e.target.value)} />
        <input className="field-half" type="number" step="0.5" min="0" placeholder="Credits"
          value={credits} onChange={(e) => setCredits(e.target.value)} />
        <select className="field-half" value={grade} onChange={(e) => setGrade(e.target.value as Grade)}>
          {GRADES.map((g) => <option key={g} value={g}>{g}</option>)}
        </select>
        <button className="btn field-full" onClick={add}>Add Course</button>
      </div>

      <ul className="list">
        {courses.length === 0 && <li className="empty-state">No courses yet</li>}
        {groups.map((grp) => (
          <div key={grp.term}>
            <li className="group-header"><span>{grp.term}</span><span>GPA {grp.gpa.toFixed(2)}</span></li>
            {grp.courses.map((c) => (
              <li key={c.id}>
                <span className="row-info">
                  <span className="pill" style={{ background: 'var(--accent-wash)', color: 'var(--accent)' }}>{c.grade}</span>
                  <span className="row-details">
                    <span className="row-name">{c.name}</span>
                    <span className="row-meta">{c.credits} credit{c.credits === 1 ? '' : 's'}</span>
                  </span>
                </span>
                <button className="icon-btn" onClick={() => remove(c.id)} aria-label={`Delete ${c.name}`}>🗑</button>
              </li>
            ))}
          </div>
        ))}
      </ul>

      <div className="gpa-number">{gpa.toFixed(2)}</div>
      <div className="gpa-caption">{totalCredits > 0 ? `Cumulative · ${totalCredits} credits` : 'Add a course to calculate'}</div>
    </div>
  );
}
