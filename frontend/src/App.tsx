import { lazy, Suspense, useCallback, type PropsWithChildren } from "react";
import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";
import { AppHeader } from "./components";
import { ReplayProvider } from "./data";
import { CurrentPageDataProvider } from "./CurrentPageDataProvider";
import { useReplay } from "./useReplay";
import { useReplayHotkeys } from "./useReplayHotkeys";
import { CommandPage, DecisionPage, HomePage, LabPage } from "./pages";
import { Phase6DemoPage } from "./Phase6DemoPage";
import "./research.css";

const ResearchPage = lazy(() => import("./ResearchPage").then((module) => ({ default: module.ResearchPage })));

export default function App() {
  return (
    <BrowserRouter>
      <RouteReplayProvider>
        <CurrentPageDataProvider>
          <div className="app-root">
            <ReplayRouteHotkeys />
            <AppHeader />
            <Routes>
              <Route path="/" element={<HomePage />} />
              <Route path="/command" element={<CommandPage />} />
              <Route path="/decision" element={<DecisionPage />} />
              <Route path="/lab" element={<LabPage />} />
              <Route path="/demo" element={<Phase6DemoPage />} />
              <Route path="/research" element={<Suspense fallback={<main className="research-page research-state" role="status">正在载入研究工作台…</main>}><ResearchPage /></Suspense>} />
              <Route path="*" element={<HomePage />} />
            </Routes>
            <footer className="global-footer">
              <span>6G / RESCUE</span>
              <span>抽象研究仿真 · 未接入真实无线网络</span>
            </footer>
          </div>
        </CurrentPageDataProvider>
      </RouteReplayProvider>
    </BrowserRouter>
  );
}

function RouteReplayProvider({ children }: PropsWithChildren) {
  const { pathname } = useLocation();
  const needsHistoricalReplay = pathname !== "/demo" && pathname !== "/research";
  return <ReplayProvider key={needsHistoricalReplay ? "historical" : "page-local"} enabled={needsHistoricalReplay}>{children}</ReplayProvider>;
}

function ReplayRouteHotkeys() {
  const { pathname } = useLocation();
  const { selectedTime, setSelectedTime, replay, setIsPlaying, togglePlayback } = useReplay();
  const enabled = pathname !== "/demo" && pathname !== "/research";
  const pause = useCallback(() => setIsPlaying(false), [setIsPlaying]);
  useReplayHotkeys({
    enabled,
    togglePlayback,
    step: (direction) => setSelectedTime(selectedTime + direction * (replay?.time_step_s ?? 10)),
    pause,
  });
  return null;
}
