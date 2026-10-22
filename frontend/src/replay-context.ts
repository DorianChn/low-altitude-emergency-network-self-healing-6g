import { createContext } from "react";
import type {
  ApiHealth,
  BenchmarkArtifact,
  ReplayArtifact,
  ReplayEvent,
  ReplayRun,
  StateSnapshot,
  Phase5BenchmarkArtifact,
  StrategyId,
} from "./types";

export interface ReplayContextValue {
  health: ApiHealth | null;
  benchmark: BenchmarkArtifact | null;
  phase5Benchmark: Phase5BenchmarkArtifact | null;
  phase5Error: string | null;
  replay: ReplayArtifact | null;
  error: string | null;
  loading: boolean;
  selectedStrategy: StrategyId;
  setSelectedStrategy: (value: StrategyId) => void;
  selectedTime: number;
  setSelectedTime: (value: number) => void;
  isPlaying: boolean;
  setIsPlaying: (value: boolean) => void;
  togglePlayback: () => void;
  playbackRate: number;
  setPlaybackRate: (value: number) => void;
  jumpToEvent: (direction: -1 | 1) => void;
  selectedRun: ReplayRun | null;
  currentFrame: StateSnapshot | null;
  timelineEvents: ReplayEvent[];
}

export const ReplayContext = createContext<ReplayContextValue | null>(null);
