import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { ReplayProvider } from "../data";
import { CurrentPageDataProvider } from "../CurrentPageDataProvider";
import { Phase6DemoPage } from "../Phase6DemoPage";
import type { Phase6DemoArtifact, Phase6DemoIndex } from "../phase6-demo-types";

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const readJson = <T,>(path: string): T => JSON.parse(readFileSync(resolve(REPO_ROOT, path), "utf8")) as T;
const demoIndex = readJson<Phase6DemoIndex>("results/phase6_demo_manifest.json");
const demoArtifacts = Object.fromEntries(
  Object.entries(demoIndex.scenarios).map(([id, item]) => [
    id,
    readJson<Phase6DemoArtifact>(`results/${item.artifact}`),
  ]),
) as Record<string, Phase6DemoArtifact>;
const historicalReplay = readJson<Record<string, unknown>>("results/phase3_replay_seed_2026.json");
const historicalBenchmark = readJson<Record<string, unknown>>("results/phase2_20_seed_results.json");
const phase5Summary = readJson<Record<string, unknown>>("results/phase5_validation_summary.json");

function response(payload: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response;
}

function TestApp() {
  return <MemoryRouter initialEntries={["/demo"]}><ReplayProvider enabled={false}><CurrentPageDataProvider><Phase6DemoPage /></CurrentPageDataProvider></ReplayProvider></MemoryRouter>;
}

function makeFetch({ missingDemoReplay = false }: { missingDemoReplay?: boolean } = {}) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/api/health") return response({ status: "ok", mode: "precomputed_offline_replay", live_stream: false, model_scope: "abstract_6g_research_simulation_not_real_network_test" });
    if (path === "/api/experiments/phase2") return response(historicalBenchmark);
    if (path === "/api/replay/2026") return response(historicalReplay);
    if (path === "/api/experiments/phase5") return response(phase5Summary);
    if (path === "/api/demo/phase6") return response(demoIndex);
    const scenario = path.split("/").at(-1) ?? "";
    if (path.startsWith("/api/demo/phase6/") && missingDemoReplay) return response({ detail: "演示回放文件缺失" }, 503);
    if (path.startsWith("/api/demo/phase6/") && demoArtifacts[scenario]) return response(demoArtifacts[scenario]);
    return response({ detail: `Unexpected test URL: ${path}` }, 404);
  });
}

beforeEach(() => {
  vi.stubGlobal("fetch", makeFetch());
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Phase6DemoPage", () => {
  it("loads frozen validation values and exposes all five strategies", async () => {
    const replay = demoArtifacts.severe_persistent_faults;
    render(<TestApp />);

    expect(await screen.findByRole("heading", { name: "严重持续故障", level: 2 })).toBeInTheDocument();
    expect(screen.getByTestId("current-replay-seed")).toHaveTextContent(/seed 7000 · \d+ 个事件时刻/);
    for (const strategyId of Object.keys(replay.strategies)) {
      expect(screen.getByTestId(`strategy-${strategyId}`)).toBeInTheDocument();
    }

    const row = screen.getByRole("row", { name: /滚动时域优化/ });
    const expected = `${(replay.strategy_aggregates.C_rolling_horizon_mpc.metrics.rescue_user_service_success_rate.mean! * 100).toFixed(2)}%`;
    expect(within(row).getByText(expected)).toBeInTheDocument();
    expect(screen.getByText(/不是训练过的机器学习模型/)).toBeInTheDocument();
  });

  it("plays saved discrete ticks, pauses, and switches strategy", async () => {
    render(<TestApp />);
    const slider = await screen.findByRole("slider", { name: "灾害网络回放时间" });
    expect(screen.getByRole("img", { name: /种子 7000 的仿真网络状态，时间 00:00/ })).toBeInTheDocument();

    fireEvent.change(slider, { target: { value: "270" } });
    await waitFor(() => expect(screen.getByRole("img", { name: /种子 7000 的仿真网络状态，时间 04:30/ })).toBeInTheDocument());

    fireEvent.click(screen.getByTestId("strategy-A_no_recovery"));
    expect(screen.getByTestId("strategy-A_no_recovery")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("img", { name: /种子 7000 的仿真网络状态，时间 04:30/ })).toBeInTheDocument();
  });

  it("switches to another recorded scenario and keeps that scenario's seed", async () => {
    render(<TestApp />);
    await screen.findByRole("heading", { name: "严重持续故障", level: 2 });
    fireEvent.change(screen.getByRole("combobox", { name: "切换灾害场景" }), { target: { value: "dynamic_failures" } });
    expect(await screen.findByRole("heading", { name: "动态故障", level: 2 })).toBeInTheDocument();
    expect(await screen.findByText(/本次轨迹 seed 7020/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /种子 7020 的仿真网络状态/ })).toBeInTheDocument();
  });

  it("opens an event record and describes frame deltas only when adjacent saved frames exist", async () => {
    render(<TestApp />);
    await screen.findByRole("heading", { name: "严重持续故障", level: 2 });
    const event = screen.getByRole("button", { name: /基站故障/ });
    fireEvent.click(event);
    expect(screen.getByRole("region", { name: "选中事件详情" })).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "选中事件详情" })).getByText(/相邻保存帧|没有同时存在的相邻记录帧/)).toBeInTheDocument();
    const causalCaveat = screen.queryByText(/不据此推断单个事件的因果效应/);
    if (causalCaveat) expect(causalCaveat).toBeInTheDocument();
    else expect(screen.getByText(/没有同时存在的相邻记录帧/)).toBeInTheDocument();
  });

  it("shows a recoverable error when a replay fixture is missing", async () => {
    vi.stubGlobal("fetch", makeFetch({ missingDemoReplay: true }));
    render(<TestApp />);
    expect(await screen.findByRole("alert")).toHaveTextContent("演示回放文件缺失");
    expect(screen.getByRole("button", { name: "重新读取数据" })).toBeEnabled();
  });
});
