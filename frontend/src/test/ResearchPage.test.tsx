import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { ResearchPage } from "../ResearchPage";
import { CurrentPageDataProvider } from "../CurrentPageDataProvider";
import { normalizeResearchArtifact, type ResearchArtifactEnvelope, type HistoricalResearchPhaseId, type ResearchPhaseId } from "../research-model";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const ARTIFACT_PATHS: Record<HistoricalResearchPhaseId, string> = {
  phase5: "results/phase5_validation_summary.json",
  phase8: "results/phase8_replication_summary.json",
  phase9: "results/phase9_corrected_confirmation_summary.json",
  phase10: "results/phase10_confirmation_summary.json",
  phase11: "results/phase11_confirmation_summary.json",
};
const artifacts = Object.fromEntries(Object.entries(ARTIFACT_PATHS).map(([phase, path]) => [
  phase,
  JSON.parse(readFileSync(resolve(ROOT, path), "utf8")) as Record<string, unknown>,
])) as Record<HistoricalResearchPhaseId, Record<string, unknown>>;
const phase14Summary = JSON.parse(readFileSync(resolve(ROOT, "results/phase14_confirmation_summary.json"), "utf8")) as Record<string, unknown>;
const phase14Sensitivity = JSON.parse(readFileSync(resolve(ROOT, "results/phase14_model_sensitivity_summary.json"), "utf8")) as Record<string, unknown>;
const phase15Summary = JSON.parse(readFileSync(resolve(ROOT, "results/phase15_calibration_summary.json"), "utf8")) as Record<string, unknown>;
const phase15Holdout = JSON.parse(readFileSync(resolve(ROOT, "results/phase15_holdout_validation.json"), "utf8")) as Record<string, unknown>;
const phase15Audit = JSON.parse(readFileSync(resolve(ROOT, "results/phase15_dataset_audit.json"), "utf8")) as Record<string, unknown>;

function envelope(phase: HistoricalResearchPhaseId): ResearchArtifactEnvelope {
  return {
    schema_version: "1.0",
    dataset_id: phase,
    artifact_path: ARTIFACT_PATHS[phase],
    artifact_sha256: "fixture-hash-from-test-file",
    experiment_role: "confirmatory_test_fixture",
    model_scope: "abstract_6g_research_simulation_not_real_network_test",
    artifact: artifacts[phase],
  };
}

function phase14Envelope(): ResearchArtifactEnvelope {
  return {
    schema_version: "1.0",
    dataset_id: "phase14",
    artifact_path: "results/phase14_confirmation_summary.json",
    artifact_sha256: "phase14-summary-hash-from-test-file",
    experiment_role: "phase14_independent_confirmation",
    model_scope: "abstract_link_budget_research_model_not_calibrated_real_6g_or_device_measurement",
    artifact: phase14Summary,
    supporting_artifacts: {
      sensitivity: {
        artifact_path: "results/phase14_model_sensitivity_summary.json",
        artifact_sha256: "phase14-sensitivity-hash-from-test-file",
        artifact: phase14Sensitivity,
      },
    },
  };
}

function phase15Envelope(): ResearchArtifactEnvelope {
  return {
    schema_version: "1.0",
    dataset_id: "phase15",
    artifact_path: "results/phase15_calibration_summary.json",
    artifact_sha256: "phase15-summary-hash-from-test-file",
    experiment_role: "public_measurement_group_holdout_evaluation",
    model_scope: "public_3p6_ghz_measurement_path_loss_evaluation_not_project_device_calibration",
    artifact: phase15Summary,
    supporting_artifacts: {
      holdout_validation: {
        artifact_path: "results/phase15_holdout_validation.json",
        artifact_sha256: "phase15-holdout-hash-from-test-file",
        artifact: phase15Holdout,
      },
      dataset_audit: {
        artifact_path: "results/phase15_dataset_audit.json",
        artifact_sha256: "phase15-audit-hash-from-test-file",
        artifact: phase15Audit,
      },
    },
  };
}

function mockResearchApi({ failPhase }: { failPhase?: ResearchPhaseId } = {}) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const phase = String(input).split("/").at(-1) as ResearchPhaseId;
    if (phase === failPhase) return { ok: false, status: 503, json: async () => ({ detail: "summary artifact unavailable" }) } as Response;
    const payload = phase === "phase14" ? phase14Envelope() : phase === "phase15" ? phase15Envelope() : envelope(phase);
    return { ok: true, status: 200, json: async () => payload } as Response;
  });
}

beforeEach(() => vi.stubGlobal("fetch", mockResearchApi()));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("ResearchPage", () => {
  it("normalizes each saved phase with its own schema and source", () => {
    for (const phase of Object.keys(ARTIFACT_PATHS) as HistoricalResearchPhaseId[]) {
      const view = normalizeResearchArtifact(envelope(phase), phase, "dynamic_failures");
      expect(view.phase).toBe(phase);
      expect(view.sourcePath).toBe(ARTIFACT_PATHS[phase]);
      expect(view.seedCount).toBeGreaterThan(0);
      expect(view.strategies.length).toBeGreaterThan(0);
      expect(view.strategies.every((strategy) => strategy.rescueService.mean === null || Number.isFinite(strategy.rescueService.mean))).toBe(true);
    }
  });

  it("renders a phase 11 scenario directly from its saved summary", async () => {
    const source = artifacts.phase11;
    const scene = (source.scenarios as Record<string, Record<string, unknown>>).dynamic_failures;
    const policy = (scene.policies as Record<string, { metrics: Record<string, { mean: number }> }>).G_centralized_coordination_uav3;
    const expected = `${(policy.metrics.rescue_user_service_success_rate.mean * 100).toFixed(2)}%`;

    render(<MemoryRouter><CurrentPageDataProvider><ResearchPage /></CurrentPageDataProvider></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "把每个结论带回证据" })).toBeInTheDocument();
    expect(screen.getAllByText("results/phase11_confirmation_summary.json").length).toBeGreaterThan(0);
    expect(screen.getByText("20 个同场景种子")).toBeInTheDocument();
    expect(screen.getAllByText(expected).length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "G · 三机集中协同" })).toBeInTheDocument();
    expect(screen.getByText(/多无人机逐帧回放不可用/)).toBeInTheDocument();
    expect(screen.getByText(/不是实测 6G 网络/)).toBeInTheDocument();
  });

  it("switches phase and presents only the saved paired contrast", async () => {
    render(<MemoryRouter><CurrentPageDataProvider><ResearchPage /></CurrentPageDataProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "G · 三机集中协同" });
    fireEvent.click(screen.getByRole("tab", { name: /Phase 9/ }));

    expect((await screen.findAllByText("results/phase9_corrected_confirmation_summary.json")).length).toBeGreaterThan(0);
    expect(await screen.findByRole("heading", { name: "E · 事件驱动恢复" })).toBeInTheDocument();
    expect(screen.getByText("−7.05 pp")).toBeInTheDocument();
    expect(screen.getByText(/Holm 校正 p = 0.000183/)).toBeInTheDocument();
  });

  it("shows an explicit unavailable state when a saved artifact cannot be read", async () => {
    vi.stubGlobal("fetch", mockResearchApi({ failPhase: "phase11" }));
    render(<MemoryRouter><CurrentPageDataProvider><ResearchPage /></CurrentPageDataProvider></MemoryRouter>);
    expect(await screen.findByRole("alert")).toHaveTextContent("summary artifact unavailable");
    expect(screen.getByRole("button", { name: "重新读取" })).toBeEnabled();
  });

  it("shows Phase 14 only from the saved paired model summary and sensitivity file", async () => {
    const scene = (phase14Summary.scenarios as Record<string, Record<string, Record<string, { rescue_user_service_success_rate: { mean: number } }>>>).dynamic_failures;
    const expected = `${(scene.G_centralized_coordination.link_budget_v1.rescue_user_service_success_rate.mean * 100).toFixed(2)}%`;
    render(<MemoryRouter><CurrentPageDataProvider><ResearchPage /></CurrentPageDataProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "G · 三机集中协同" });
    fireEvent.click(screen.getByRole("tab", { name: /Phase 14/ }));

    expect(await screen.findByRole("heading", { name: "链路预算如何改变服务判断" })).toBeInTheDocument();
    expect(screen.getByText((_, element) => element?.tagName === "P" && element.textContent?.includes("20 个确认种子") === true)).toBeInTheDocument();
    expect(screen.getAllByText(expected).length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "参数敏感性筛查" }).closest("article")).toHaveTextContent("开发种子配对差");
    expect(screen.getAllByText(/抽象假设/).length).toBeGreaterThan(0);
    fireEvent.change(screen.getByRole("combobox", { name: "选择灾害场景" }), { target: { value: "high_mobility_rescue" } });
    expect(await screen.findByText((_, element) => element?.tagName === "P" && element.textContent?.includes("高移动救援") === true)).toBeInTheDocument();
  });

  it("renders Phase 15 only from saved public measurements and discloses missing device calibration", async () => {
    render(<MemoryRouter><CurrentPageDataProvider><ResearchPage /></CurrentPageDataProvider></MemoryRouter>);
    await screen.findByRole("heading", { name: "G · 三机集中协同" });
    fireEvent.click(screen.getByRole("tab", { name: /Phase 15/ }));

    expect(await screen.findByRole("heading", { name: "有留出结果；项目设备未校准" })).toBeInTheDocument();
    expect(screen.getByText("1.82 dB")).toBeInTheDocument();
    expect(screen.getAllByText("7.19 dB").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("-5.05 dB").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/NOT_CALIBRATED/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "相同 570 条留出样本的误差对照" })).toBeInTheDocument();
    expect(screen.getAllByText(/测量不确定度/).length).toBeGreaterThanOrEqual(2);
    expect(screen.getByAltText(/预测路径损耗残差分布/)).toHaveAttribute("src", "/api/research/phase15/plots/phase15_holdout_residuals.png");
  });
});
