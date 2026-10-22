import { useContext } from "react";
import { ReplayContext } from "./replay-context";

export function useReplay() {
  const context = useContext(ReplayContext);
  if (!context) throw new Error("useReplay must be used inside ReplayProvider");
  return context;
}
