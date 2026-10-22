import { useEffect, useLayoutEffect, useRef } from "react";

export interface ReplayHotkeyController {
  enabled: boolean;
  togglePlayback: () => void;
  step: (direction: -1 | 1) => void;
  pause: () => void;
}

function eventComesFromInteractiveTarget(event: KeyboardEvent): boolean {
  return event.composedPath().some((target) => {
    if (!(target instanceof Element)) return false;
    if (target instanceof HTMLElement && target.isContentEditable) return true;
    return target.matches("input, textarea, select, button, a[href], [role='button'], [role='slider'], [contenteditable='true']");
  });
}

export function useReplayHotkeys(controller: ReplayHotkeyController) {
  const { enabled, togglePlayback, step, pause } = controller;
  const controllerRef = useRef(controller);
  useLayoutEffect(() => { controllerRef.current = { enabled, togglePlayback, step, pause }; }, [enabled, togglePlayback, step, pause]);

  useEffect(() => {
    const pauseIfHidden = () => {
      if (document.visibilityState === "hidden") controllerRef.current.pause();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      const active = controllerRef.current;
      if (!active.enabled || event.defaultPrevented || event.isComposing || eventComesFromInteractiveTarget(event)) return;
      if (event.ctrlKey || event.altKey || event.metaKey || event.getModifierState("AltGraph")) return;
      if (event.code === "Space" || event.key === " ") {
        if (event.repeat) return;
        event.preventDefault();
        active.togglePlayback();
      } else if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        if (event.repeat) return;
        event.preventDefault();
        active.step(event.key === "ArrowRight" ? 1 : -1);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    document.addEventListener("visibilitychange", pauseIfHidden);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      document.removeEventListener("visibilitychange", pauseIfHidden);
    };
  }, []);

  useEffect(() => {
    if (!enabled || document.visibilityState === "hidden") pause();
  }, [enabled, pause]);

  useEffect(() => () => pause(), [pause]);
}
