import { useMemo, useState } from 'react';
import { useStore } from '../state/useStore';
import type { Expense, ExpenseCategory } from '../lib/types';
import { formatShortDate, parseISODate, todayISO } from '../lib/dates';

const CATEGORIES: Record<ExpenseCategory, { label: string; color: string }> = {
  food: { label: 'Food', color: '#ff7675' },
  transport: { label: 'Transport', color: '#4d96ff' },
  fun: { label: 'Fun', color: '#f6b93b' },
  other: { label: 'Other', color: '#9b7bf0' },
};

export function Expenses() {
  const [expenses, setExpenses] = useStore('college-toolkit:expenses', [] as Expense[]);
  const [name, setName] = useState('');
  const [amount, setAmount] = useState('');
  const [category, setCategory] = useState<ExpenseCategory>('food');
  const [date, setDate] = useState(todayISO());

  const nextId = useMemo(() => expenses.reduce((m, e) => Math.max(m, e.id), 0) + 1, [expenses]);

  function add() {
    const amt = parseFloat(amount);
    if (!name.trim() || isNaN(amt)) return;
    setExpenses([...expenses, { id: nextId, name: name.trim(), amount: amt, category, date: date || todayISO() }]);
    setName('');
    setAmount('');
  }

  function remove(id: number) {
    setExpenses(expenses.filter((e) => e.id !== id));
  }

  const monthKey = todayISO().slice(0, 7);
  const inMonth = expenses.filter((e) => e.date.slice(0, 7) === monthKey);
  const sorted = [...inMonth].sort((a, b) => b.date.localeCompare(a.date) || b.id - a.id);
  const monthTotal = inMonth.reduce((s, e) => s + e.amount, 0);

  return (
    <div className="card">
      <h1 className="page-title">Expenses</h1>
      <p className="page-sub">Track spending by category and day.</p>

      <div className="field-row">
        <input className="field-full" placeholder="Expense name" value={name}
          onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
        <input className="field-full" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        <input className="field-half" type="number" step="0.01" inputMode="decimal" placeholder="Amount"
          value={amount} onChange={(e) => setAmount(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} />
        <select className="field-half" value={category} onChange={(e) => setCategory(e.target.value as ExpenseCategory)}>
          {(Object.keys(CATEGORIES) as ExpenseCategory[]).map((k) => (
            <option key={k} value={k}>{CATEGORIES[k].label}</option>
          ))}
        </select>
        <button className="btn field-full" onClick={add}>Add</button>
      </div>

      <ul className="list">
        {sorted.length === 0 && <li className="empty-state">No expenses this month yet</li>}
        {sorted.map((e) => {
          const cat = CATEGORIES[e.category] ?? CATEGORIES.other;
          return (
            <li key={e.id}>
              <span className="row-info">
                <span className="pill" style={{ background: cat.color + '22', color: cat.color }}>{cat.label}</span>
                <span className="row-details">
                  <span className="row-name">{e.name}</span>
                  <span className="row-meta">{formatShortDate(e.date)}</span>
                </span>
              </span>
              <span className="row-right">
                <span className="row-amount">${e.amount.toFixed(2)}</span>
                <button className="icon-btn" onClick={() => remove(e.id)} aria-label={`Delete ${e.name}`}>🗑</button>
              </span>
            </li>
          );
        })}
      </ul>

      <div className="total-row">
        <span>{parseISODate(monthKey + '-01').toLocaleDateString('en-US', { month: 'long' })} Total</span>
        <span>${monthTotal.toFixed(2)}</span>
      </div>
    </div>
  );
}
