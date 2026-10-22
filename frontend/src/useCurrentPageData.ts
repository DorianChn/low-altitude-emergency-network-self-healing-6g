import { useContext } from "react";
import { CurrentPageDataContext } from "./current-data-context";

export function useCurrentPageData() {
  const context = useContext(CurrentPageDataContext);
  if (!context) throw new Error("useCurrentPageData must be used inside CurrentPageDataProvider");
  return context;
}
