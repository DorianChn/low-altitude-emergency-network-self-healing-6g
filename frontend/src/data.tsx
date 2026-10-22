import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type PropsWithChildren,
} from "react";
import { ReplayContext, type ReplayContextValue } from "./replay-context";
import type {
  ApiHealth,
  BenchmarkArtifact,
  Phase5BenchmarkArtifact,
  ReplayArtifact,
  StrategyId,
} from "./types";

async function fetchJson<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  if (!response.ok) {
    const detail = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(detail?.detail ?? `接口返回 ${response.status}：${path}`);
  }
  return response.json() as Promise<T>;
}

export function ReplayProvider({ children, enabled = true }: PropsWithChildren<{ enabled?: boolean }>) {
  const [health, setHealth] = useState<ApiHealth | null>(null);
  const [benchmark, setBenchmark] = useState<BenchmarkArtifact | null>(null);
  const [phase5Benchmark, setPhase5Benchmark] = useState<Phase5BenchmarkArtifact | null>(null);
  const [phase5Error, setPhase5Error] = useState<string | null>(null);
  const [replay, setReplay] = useState<ReplayArtifact | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedStrategy, setSelectedStrategy] = useState<StrategyId>("C_rolling_horizon_mpc");
  const [selectedTime, setSelectedTimeInternal] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    const phase5Request = fetchJson<Phase5BenchmarkArtifact>("/api/experiments/phase5", controller.signal)
      .then((artifact) => ({ artifact, error: null as string | null }))
      .catch((cause: unknown) => ({
        artifact: null,
        error: cause instanceof Error ? cause.message : "无法读取第五阶段验证结果",
      }));
    Promise.all([
      fetchJson<ApiHealth>("/api/health", controller.signal),
      fetchJson<BenchmarkArtifact>("/api/experiments/phase2", controller.signal),
      fetchJson<ReplayArtifact>("/api/replay/2026", controller.signal),
      phase5Request,
    ])
      .then(([nextHealth, nextBenchmark, nextReplay, nextPhase5]) => {
        setHealth(nextHealth);
        setBenchmark(nextBenchmark);
        setPhase5Benchmark(nextPhase5.artifact);
        setPhase5Error(nextPhase5.error);
        setReplay(nextReplay);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(cause instanceof Error ? cause.message : "无法读取仿真数据接口");
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [enabled]);

  const setSelectedTime = useCallback((value: number) => {
    setSelectedTimeInternal(() => {
      if (!replay) return Math.max(0, value);
      const step = replay.time_step_s;
      const clamped = Math.max(0, Math.min(replay.duration_s, value));
      return Math.round(clamped / step) * step;
    });
  }, [replay]);

  const selectedRun = replay?.strategies[selectedStrategy] ?? null;
  const currentIndex = replay
    ? Math.min(
        Math.max(0, Math.round(selectedTime / replay.time_step_s)),
        Math.max(0, (selectedRun?.state_snapshots.length ?? 1) - 1),
      )
    : 0;
  const currentFrame = selectedRun?.state_snapshots[currentIndex] ?? null;

  useEffect(() => {
    if (!isPlaying || !replay || selectedTime >= replay.duration_s) return;
    const timer = window.setTimeout(() => {
      setSelectedTime(selectedTime + replay.time_step_s);
    }, 1000 / playbackRate);
    return () => window.clearTimeout(timer);
  }, [isPlaying, playbackRate, replay, selectedTime, setSelectedTime]);

  const timelineEvents = useMemo(() => {
    if (!replay || !selectedRun) return [];
    const scheduled = replay.environment_events.filter((event) => event.source === "configured_event_schedule");
    return [...scheduled, ...selectedRun.event_log].sort(
      (a, b) => a.time_s - b.time_s || a.event_type.localeCompare(b.event_type),
    );
  }, [replay, selectedRun]);

  const jumpToEvent = useCallback((direction: -1 | 1) => {
    const times = [...new Set(timelineEvents.map((event) => event.time_s))].sort((a, b) => a - b);
    if (direction > 0) {
      const next = times.find((time) => time > selectedTime);
      setSelectedTime(next ?? 0);
    } else {
      const previous = [...times].reverse().find((time) => time < selectedTime);
      setSelectedTime(previous ?? 0);
    }
  }, [selectedTime, setSelectedTime, timelineEvents]);

  const togglePlayback = useCallback(() => {
    if (!replay) return;
    if (selectedTime >= replay.duration_s) setSelectedTime(0);
    setIsPlaying((value) => !value || selectedTime >= replay.duration_s);
  }, [replay, selectedTime, setSelectedTime]);

  const value: ReplayContextValue = {
    health,
    benchmark,
    phase5Benchmark,
    phase5Error,
    replay,
    error,
    loading,
    selectedStrategy,
    setSelectedStrategy,
    selectedTime,
    setSelectedTime,
    isPlaying: Boolean(replay && isPlaying && selectedTime < replay.duration_s),
    setIsPlaying,
    togglePlayback,
    playbackRate,
    setPlaybackRate,
    jumpToEvent,
    selectedRun,
    currentFrame,
    timelineEvents,
  };

  return <ReplayContext.Provider value={value}>{children}</ReplayContext.Provider>;
}
