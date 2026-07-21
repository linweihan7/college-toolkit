// Pure last-write-wins merge decision, extracted so it can be unit-tested without
// a network or a Supabase client.

export interface RemoteRow {
  key: string;
  value: unknown;
  updated_at: string; // ISO timestamp
}

export interface MergeDecision {
  applyFromRemote: { key: string; value: unknown; ts: number }[]; // remote is newer -> overwrite local
  pushToRemote: string[]; // local is newer or remote missing -> push local up
}

// localMeta: key -> local last-write ms. localKeys: keys that exist locally.
// dataKeys: the allowed keys (ignore anything else the server returns).
export function mergeDecision(
  localMeta: Record<string, number>,
  localKeys: string[],
  remoteRows: RemoteRow[],
  dataKeys: string[]
): MergeDecision {
  const applyFromRemote: MergeDecision['applyFromRemote'] = [];
  const settled = new Set<string>();

  for (const row of remoteRows) {
    if (!dataKeys.includes(row.key)) continue;
    const remoteT = new Date(row.updated_at).getTime();
    const localT = localMeta[row.key] || 0;
    if (remoteT > localT) {
      applyFromRemote.push({ key: row.key, value: row.value, ts: remoteT });
      settled.add(row.key);
    } else if (remoteT === localT) {
      settled.add(row.key);
    }
    // remoteT < localT: local wins -> leave unsettled so it gets pushed
  }

  // Anything present locally that the remote didn't already settle needs pushing.
  const pushToRemote = localKeys.filter((k) => dataKeys.includes(k) && !settled.has(k));

  return { applyFromRemote, pushToRemote };
}
