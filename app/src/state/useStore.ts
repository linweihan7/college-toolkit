// React binding over the storage layer. Any component calling useStore for a key
// re-renders whenever that key changes — including changes from another tab/device
// applied by the sync engine. Built on useSyncExternalStore so it's concurrent-safe.

import { useCallback, useSyncExternalStore } from 'react';
import type { DataKey, DataShape } from '../lib/types';
import { save, subscribe } from './storage';

export function useStore<K extends DataKey>(
  key: K,
  fallback: DataShape[K]
): [DataShape[K], (value: DataShape[K]) => void] {
  // Cache the parsed snapshot; only recompute when the raw string changes, so
  // useSyncExternalStore sees a stable reference and doesn't loop.
  const getSnapshot = useCallback(() => {
    const raw = localStorage.getItem(key);
    if (raw === lastRaw[key]) return lastValue[key] as DataShape[K];
    lastRaw[key] = raw;
    lastValue[key] = raw === null ? fallback : safeParse(raw, fallback);
    return lastValue[key] as DataShape[K];
  }, [key, fallback]);

  const value = useSyncExternalStore(
    (cb) => subscribe(key, cb),
    getSnapshot,
    getSnapshot
  );

  const setValue = useCallback((next: DataShape[K]) => save(key, next), [key]);

  return [value, setValue];
}

const lastRaw: Record<string, string | null> = {};
const lastValue: Record<string, unknown> = {};

function safeParse<T>(raw: string, fallback: T): T {
  try {
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}
