import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useReplayHotkeys } from "../useReplayHotkeys";

function Harness({ enabled, toggle, step, pause }: { enabled: boolean; toggle: () => void; step: (direction: -1 | 1) => void; pause: () => void }) {
  const [value, setValue] = useState(0);
  useReplayHotkeys({ enabled, togglePlayback: toggle, step, pause });
  return <><p data-testid="value">{value}</p><button onClick={() => setValue((current) => current + 1)}>focus target</button><input aria-label="editable" /><select aria-label="choice"><option>one</option></select><div contentEditable aria-label="rich text" /></>;
}

describe("replay hotkeys", () => {
  it("toggles and steps only when focus is outside controls", () => {
    const toggle = vi.fn(); const step = vi.fn(); const pause = vi.fn();
    render(<Harness enabled toggle={toggle} step={step} pause={pause} />);
    fireEvent.keyDown(window, { code: "Space", key: " " });
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(toggle).toHaveBeenCalledTimes(1);
    expect(step).toHaveBeenCalledWith(1);

    screen.getByRole("button", { name: "focus target" }).focus();
    const button = screen.getByRole("button", { name: "focus target" });
    fireEvent.keyDown(button, { code: "Space", key: " " });
    const input = screen.getByRole("textbox", { name: "editable" });
    input.focus();
    fireEvent.keyDown(input, { key: "ArrowLeft" });
    const select = screen.getByRole("combobox", { name: "choice" });
    select.focus();
    fireEvent.keyDown(select, { code: "Space", key: " " });
    const richText = screen.getByLabelText("rich text");
    richText.focus();
    fireEvent.keyDown(richText, { key: "ArrowRight" });
    fireEvent.keyDown(window, { key: "ArrowRight", ctrlKey: true });
    fireEvent.keyDown(window, { key: "ArrowRight", altKey: true });
    fireEvent.keyDown(window, { key: "ArrowRight", metaKey: true });
    fireEvent.keyDown(window, { code: "Space", key: " ", isComposing: true });
    expect(toggle).toHaveBeenCalledTimes(1);
    expect(step).toHaveBeenCalledTimes(1);
  });

  it("pauses on route disable and ignores repeated space keydown", () => {
    const toggle = vi.fn(); const step = vi.fn(); const pause = vi.fn();
    const view = render(<Harness enabled toggle={toggle} step={step} pause={pause} />);
    fireEvent.keyDown(window, { code: "Space", key: " ", repeat: true });
    expect(toggle).not.toHaveBeenCalled();
    view.rerender(<Harness enabled={false} toggle={toggle} step={step} pause={pause} />);
    expect(pause).toHaveBeenCalled();
    fireEvent.keyDown(window, { key: "ArrowRight" });
    expect(step).not.toHaveBeenCalled();
  });

  it("pauses when the document becomes hidden", () => {
    const toggle = vi.fn(); const step = vi.fn(); const pause = vi.fn();
    render(<Harness enabled toggle={toggle} step={step} pause={pause} />);
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    pause.mockClear();
    fireEvent(document, new Event("visibilitychange"));
    expect(pause).toHaveBeenCalledTimes(1);
    delete (document as Document & { visibilityState?: DocumentVisibilityState }).visibilityState;
  });
});
