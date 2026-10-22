import "@testing-library/jest-dom/vitest";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { cleanup, render, screen, fireEvent, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Phase17ResearchSection } from "../Phase17ResearchSection";
import type { ResearchArtifactEnvelope } from "./research-model";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const json = (path: string) => JSON.parse(readFileSync(resolve(ROOT, path), "utf8")) as Record<string, unknown>;
const artifact = json("results/phase17_validation_summary.json");
const paths = {
  environment_inventory: "phase17_environment_inventory.json",
  integrity_audit: "phase17_integrity_audit.json",
  adapter_status: "phase17_adapter_status.json",
  closed_loop_run: "phase17_closed_loop_run.json",
  command_audit: "phase17_command_audit.json",
  fault_injection_results: "phase17_fault_injection_results.json",
  offline_replay_validation: "phase17_replay_validation.json",
} as const;
const envelope: ResearchArtifactEnvelope = {
  schema_version: "1.0",
  dataset_id: "phase17",
  artifact_path: "results/phase17_validation_summary.json",
  artifact_sha256: "saved-test-evidence",
  experiment_role: "software_acceptance_fixture",
  model_scope: "software_closed_loop_and_saved_replay_validation_not_real_hil",
  artifact,
  supporting_artifacts: Object.fromEntries(Object.entries(paths).map(([key, filename]) => [key, {
    artifact_path: `results/${filename}`,
    artifact_sha256: "saved-test-evidence",
    artifact: json(`results/${filename}`),
  }])),
};

describe("Phase17ResearchSection", () => {
  afterEach(cleanup);

  it("renders saved readiness evidence without claiming a physical HIL run", () => {
    render(<Phase17ResearchSection envelope={envelope} />);
    expect(screen.getByText("当前仅完成软件闭环与记录回放验证。真实硬件在环测试尚未完成。")).toBeVisible();
    expect(screen.getByText("OUTPUT DISABLED")).toBeVisible();
    expect(screen.getByText("未执行")).toBeVisible();
    expect(screen.getByText("受保护历史文件 182 项")).toBeVisible();
    expect(screen.getByText("21 / 21")).toBeVisible();
    expect(screen.getByText(/不对中间状态插值/)).toBeVisible();
  });

  it("steps through exact saved frames and selects fault injection evidence", () => {
    render(<Phase17ResearchSection envelope={envelope} />);
    const replayState = screen.getByTestId("phase17-replay-state");
    expect(within(replayState).getByText("帧 1 / 61")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "单步前进" }));
    expect(within(replayState).getByText("帧 2 / 61")).toBeVisible();
    fireEvent.change(screen.getByRole("slider", { name: "已保存的离散回放帧" }), { target: { value: "60" } });
    expect(within(replayState).getByText("帧 61 / 61")).toBeVisible();
    fireEvent.change(screen.getByRole("combobox", { name: "选择故障注入案例" }), { target: { value: "20" } });
    expect(screen.getAllByText("SERVICE_RESTORED_AFTER_BACKHAUL_RECOVERY")).toHaveLength(2);
  });
});
