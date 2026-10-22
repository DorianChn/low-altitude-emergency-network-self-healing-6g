import type { ReplayEvent, StrategyId } from "./types";

export function formatTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.floor(seconds % 60);
  return String(minutes).padStart(2, "0") + ":" + String(remaining).padStart(2, "0");
}

export function strategyLabel(strategy: StrategyId): string {
  if (strategy === "A_no_recovery") return "A · 无恢复";
  if (strategy === "B_phase1_static_grid") return "B · 静态网格";
  return "C · 滚动优化";
}

export function eventLabel(event: ReplayEvent): string {
  const labels: Record<string, string> = {
    station_failure: "基站故障",
    station_recovery: "基站恢复",
    traffic_change: "业务负载变化",
    backhaul_failure: "无人机回传中断",
    backhaul_recovery: "无人机回传恢复",
    optimizer_decision: "智能调度决策",
    drone_state_update: "无人机状态更新",
  };
  return labels[event.event_type] ?? event.event_type.replaceAll("_", " ");
}
