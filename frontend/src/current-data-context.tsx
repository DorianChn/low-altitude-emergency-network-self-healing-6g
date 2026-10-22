import { createContext } from "react";

export type PageDataMode = "single-seed" | "multi-seed" | "historical";
export type PageDataStatus = "loading" | "ready" | "error";

export interface CurrentPageData {
  ownerId: string;
  sourceId: string;
  sourceLabel: string;
  mode: PageDataMode;
  status: PageDataStatus;
  seed: number | null;
  scenarioId?: string;
  scenarioLabel?: string;
  strategyId?: string;
  error?: string | null;
}

interface CurrentPageDataValue {
  current: CurrentPageData | null;
  register: (ownerId: string, value: Omit<CurrentPageData, "ownerId">) => void;
  clear: (ownerId: string) => void;
}

export const CurrentPageDataContext = createContext<CurrentPageDataValue | null>(null);
