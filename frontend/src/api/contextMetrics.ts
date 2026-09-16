const API_BASE = import.meta.env.VITE_API_URL ?? "";

export interface ContextMetrics {
  used_tokens: number;
  max_tokens: number;
  cache_hit_rate: number;
  compaction_events: {
    L1: number;
    L2: number;
    L3: number;
    L4: number;
    L5: number;
  };
  offloaded_files: string[];
  total_cost_usd: number;
}

export async function fetchContextMetrics(
  sessionId: string
): Promise<ContextMetrics> {
  const resp = await fetch(
    `${API_BASE}/api/metrics/context?session_id=${encodeURIComponent(sessionId)}`
  );
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
  return resp.json();
}