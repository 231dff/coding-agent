import type { TimeRange, TimeseriesResponse } from "@/types/metrics";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

export async function fetchTimeseries(
  range: TimeRange
): Promise<TimeseriesResponse> {
  const resp = await fetch(
    `${API_BASE}/api/metrics/timeseries?range=${encodeURIComponent(range)}`
  );
  if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
  return resp.json();
}