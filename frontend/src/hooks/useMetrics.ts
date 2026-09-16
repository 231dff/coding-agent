import { useQuery } from "@tanstack/react-query";
import { fetchTimeseries } from "@/api/metrics";
import type { TimeRange } from "@/types/metrics";

/**
 * 拉取时序指标。
 *
 * @param range 时间范围
 * @param refetchInterval 自动刷新间隔（毫秒），0 表示不刷新
 */
export function useMetrics(range: TimeRange, refetchInterval = 15_000) {
  return useQuery({
    queryKey: ["metrics-timeseries", range],
    queryFn: () => fetchTimeseries(range),
    refetchInterval: refetchInterval > 0 ? refetchInterval : false,
    staleTime: 5_000,
  });
}