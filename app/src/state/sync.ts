// Optional cloud sync. The shared state layer (storage.ts) is the seam: this
// module registers a write hook and mirrors changed keys to Supabase with the
// last-write-wins decision from sync-merge.ts (which is unit-tested). Everything
// no-ops cleanly when no connection is configured, so the app is fully functional
// logged out — exactly as in the current single-file build.

import type { DataKey } from '../lib/types';
import { DATA_KEYS } from '../lib/types';
import { applyRemote, readMeta, registerSyncHook, writeMeta } from './storage';
import { mergeDecision, type RemoteRow } from '../lib/sync-merge';

interface Config { url: string; anonKey: string; }
const CONFIG_KEY = 'college-toolkit:supabase-config';
const TABLE = 'toolkit_data';

type SupabaseClient = {
  auth: {
    getSession(): Promise<{ data: { session: Session | null } }>;
    onAuthStateChange(cb: (event: string, s: Session | null) => void): unknown;
  };
  from(table: string): {
    upsert(rows: unknown[]): Promise<{ error: { message: string } | null }>;
    select(cols: string): Promise<{ data: RemoteRow[] | null; error: { message: string } | null }>;
  };
};
interface Session { user: { id: string; email?: string }; }

let client: SupabaseClient | null = null;
let session: Session | null = null;
const dirty = new Set<DataKey>();
let pushTimer: ReturnType<typeof setTimeout> | null = null;

function readConfig(): Config | null {
  try {
    const raw = localStorage.getItem(CONFIG_KEY);
    return raw ? (JSON.parse(raw) as Config) : null;
  } catch {
    return null;
  }
}

async function pushDirty(): Promise<void> {
  if (!client || !session || dirty.size === 0) return;
  const meta = readMeta();
  const rows = [...dirty].map((key) => ({
    user_id: session!.user.id,
    key,
    value: JSON.parse(localStorage.getItem(key) || 'null'),
    updated_at: new Date(meta[key] || Date.now()).toISOString(),
  }));
  const { error } = await client.from(TABLE).upsert(rows);
  if (!error) dirty.clear();
}

async function pullAll(): Promise<void> {
  if (!client || !session) return;
  const { data, error } = await client.from(TABLE).select('key,value,updated_at');
  if (error || !data) return;
  const meta = readMeta();
  const localKeys = DATA_KEYS.filter((k) => localStorage.getItem(k) !== null);
  const decision = mergeDecision(meta, localKeys, data, DATA_KEYS);
  decision.applyFromRemote.forEach(({ key, value, ts }) => {
    applyRemote(key as DataKey, value as never);
    meta[key] = ts;
  });
  writeMeta(meta);
  decision.pushToRemote.forEach((k) => dirty.add(k as DataKey));
  await pushDirty();
}

// Wired from main so the state layer notifies us of local writes.
registerSyncHook((key) => {
  if (!client || !session) return;
  dirty.add(key);
  if (pushTimer) clearTimeout(pushTimer);
  pushTimer = setTimeout(pushDirty, 2000);
});

export async function initSync(): Promise<void> {
  const config = readConfig();
  if (!config) return; // logged-out / unconfigured: no-op
  try {
    const mod = await import('@supabase/supabase-js');
    client = mod.createClient(config.url, config.anonKey) as unknown as SupabaseClient;
    client.auth.onAuthStateChange((_event, s) => {
      session = s;
      if (s) void pullAll();
    });
    const { data } = await client.auth.getSession();
    session = data.session;
    if (session) await pullAll();
  } catch (err) {
    console.warn('Cloud sync unavailable', err);
  }
}
