import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CurrentPageDataProvider } from "../CurrentPageDataProvider";
import { useCurrentPageData } from "../useCurrentPageData";

function Harness() {
  const { current, register, clear } = useCurrentPageData();
  return <><output>{current?.sourceId ?? "empty"}</output><button onClick={() => register("demo", { sourceId: "seed-1", sourceLabel: "frozen replay", mode: "single-seed", status: "ready", seed: 1 })}>register</button><button onClick={() => clear("other-page")}>clear other</button><button onClick={() => clear("demo")}>clear owner</button></>;
}

describe("current page data ownership", () => {
  it("retains the active page context when an unrelated page cleanup runs", () => {
    render(<CurrentPageDataProvider><Harness /></CurrentPageDataProvider>);
    fireEvent.click(screen.getByRole("button", { name: "register" }));
    fireEvent.click(screen.getByRole("button", { name: "clear other" }));
    expect(screen.getByText("seed-1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "clear owner" }));
    expect(screen.getByText("empty")).toBeInTheDocument();
  });
});
