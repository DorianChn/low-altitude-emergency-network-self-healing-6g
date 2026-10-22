import { useCallback, useMemo, useState, type PropsWithChildren } from "react";
import { CurrentPageDataContext, type CurrentPageData } from "./current-data-context";

export function CurrentPageDataProvider({ children }: PropsWithChildren) {
  const [current, setCurrent] = useState<CurrentPageData | null>(null);
  const register = useCallback((ownerId: string, value: Omit<CurrentPageData, "ownerId">) => {
    setCurrent({ ownerId, ...value });
  }, []);
  const clear = useCallback((ownerId: string) => {
    setCurrent((value) => value?.ownerId === ownerId ? null : value);
  }, []);
  const value = useMemo(() => ({ current, register, clear }), [current, register, clear]);
  return <CurrentPageDataContext.Provider value={value}>{children}</CurrentPageDataContext.Provider>;
}
