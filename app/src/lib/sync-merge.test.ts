import { describe, it, expect } from 'vitest';
import { mergeDecision, type RemoteRow } from './sync-merge';

const DATA_KEYS = ['college-toolkit:expenses', 'college-toolkit:todos', 'college-toolkit:gpa'];
const iso = (ms: number) => new Date(ms).toISOString();

describe('mergeDecision (last-write-wins)', () => {
  it('applies a newer remote row over local', () => {
    const local = { 'college-toolkit:expenses': 1000 };
    const remote: RemoteRow[] = [{ key: 'college-toolkit:expenses', value: [{ id: 1 }], updated_at: iso(2000) }];
    const d = mergeDecision(local, ['college-toolkit:expenses'], remote, DATA_KEYS);
    expect(d.applyFromRemote.map((r) => r.key)).toEqual(['college-toolkit:expenses']);
    expect(d.pushToRemote).toEqual([]);
  });

  it('keeps and pushes local when local is newer', () => {
    const local = { 'college-toolkit:expenses': 5000 };
    const remote: RemoteRow[] = [{ key: 'college-toolkit:expenses', value: [], updated_at: iso(2000) }];
    const d = mergeDecision(local, ['college-toolkit:expenses'], remote, DATA_KEYS);
    expect(d.applyFromRemote).toEqual([]);
    expect(d.pushToRemote).toEqual(['college-toolkit:expenses']);
  });

  it('pulls a key that exists only on the remote', () => {
    const remote: RemoteRow[] = [{ key: 'college-toolkit:todos', value: [{ id: 9 }], updated_at: iso(3000) }];
    const d = mergeDecision({}, [], remote, DATA_KEYS);
    expect(d.applyFromRemote.map((r) => r.key)).toEqual(['college-toolkit:todos']);
  });

  it('pushes a local-only key the remote has never seen', () => {
    const d = mergeDecision({ 'college-toolkit:gpa': 100 }, ['college-toolkit:gpa'], [], DATA_KEYS);
    expect(d.pushToRemote).toEqual(['college-toolkit:gpa']);
  });

  it('equal timestamps settle with no work', () => {
    const remote: RemoteRow[] = [{ key: 'college-toolkit:expenses', value: [], updated_at: iso(4000) }];
    const d = mergeDecision({ 'college-toolkit:expenses': 4000 }, ['college-toolkit:expenses'], remote, DATA_KEYS);
    expect(d.applyFromRemote).toEqual([]);
    expect(d.pushToRemote).toEqual([]);
  });

  it('ignores unknown keys from the server', () => {
    const remote: RemoteRow[] = [{ key: 'college-toolkit:evil', value: 1, updated_at: iso(9000) }];
    const d = mergeDecision({}, [], remote, DATA_KEYS);
    expect(d.applyFromRemote).toEqual([]);
  });
});
