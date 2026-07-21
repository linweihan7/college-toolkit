// The persistence layer: typed localStorage access with change notifications and
// per-key "last written locally" timestamps that the sync engine reads for
// last-write-wins. This is the single seam every feature and the cloud sync
// share, so nothing reaches into localStorage directly.

import type { DataKey, DataShape } from '../lib/types';

const META_KEY = 'college-toolkit:sync-meta';

type Listener = () => void;
const listeners = new Map<DataKey, Set<Listener>>();
const globalListeners = new Set<Listener>();

// Sync engine registers here to hear about local writes (avoids a hard dependency
// on the sync module, which is optional).
let onWrite: ((key: DataKey) => void) | null = null;
export function registerSyncHook(fn: (key: DataKey) => void) {
  onWrite = fn;
}

export function load<K extends DataKey>(key: K, fallback: DataShape[K]): DataShape[K] {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as DataShape[K]);
  } catch {
    return fallback;
  }
}

export function save<K extends DataKey>(key: K, value: DataShape[K]): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    stampMeta(key);
  } catch (err) {
    console.warn('Could not save', key, err);
    return;
  }
  notify(key);
  onWrite?.(key);
}

// Called by the sync engine when a remote value is applied, so the UI refreshes
// without re-stamping the local timestamp (which would defeat last-write-wins).
export function applyRemote<K extends DataKey>(key: K, value: DataShape[K]): void {
  localStorage.setItem(key, JSON.stringify(value));
  notify(key);
}

export function readMeta(): Record<string, number> {
  try {
    return JSON.parse(localStorage.getItem(META_KEY) || '{}');
  } catch {
    return {};
  }
}

function stampMeta(key: DataKey): void {
  const meta = readMeta();
  meta[key] = Date.now();
  localStorage.setItem(META_KEY, JSON.stringify(meta));
}

export function writeMeta(meta: Record<string, number>): void {
  localStorage.setItem(META_KEY, JSON.stringify(meta));
}

function notify(key: DataKey): void {
  listeners.get(key)?.forEach((l) => l());
  globalListeners.forEach((l) => l());
}

export function subscribe(key: DataKey, listener: Listener): () => void {
  if (!listeners.has(key)) listeners.set(key, new Set());
  listeners.get(key)!.add(listener);
  return () => listeners.get(key)!.delete(listener);
}

export function subscribeAll(listener: Listener): () => void {
  globalListeners.add(listener);
  return () => globalListeners.delete(listener);
}
