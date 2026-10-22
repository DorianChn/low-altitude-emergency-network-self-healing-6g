import "@testing-library/jest-dom/vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Phase18ResearchSection } from "../Phase18ResearchSection";
import type { ResearchArtifactEnvelope } from "../research-model";

const ROOT = resolve(import.meta.dirname, "../../..");
const read = (path: string) => JSON.parse(readFileSync(resolve(ROOT, path), "utf8")) as Record<string, unknown>;

function savedEnvelope(): ResearchArtifactEnvelope {
  const paths = {
    integrity_audit: "results/phase18/phase18_integrity_audit.json",
    evidence_manifest: "results/phase18/phase18_evidence_manifest.json",
    release_manifest: "results/phase18/phase18_release_manifest.json",
  };
  return {
    schema_version: "1.0",
    dataset_id: "phase18",
    artifact_path: "results/phase18/phase18_validation_summary.json",
    artifact_sha256: "fixture-hash",
    experiment_role: "saved_final_audit",
    model_scope: "abstract_research_simulation_not_real_network_test",
    artifact: read("results/phase18/phase18_validation_summary.json"),
    supporting_artifacts: Object.fromEntries(Object.entries(paths).map(([key, path]) => [key, {
      artifact_path: path,
      artifact_sha256: "support-hash",
      artifact: read(path),
    }])),
  };
}

describe("Phase18ResearchSection", () => {
  afterEach(cleanup);

  it("renders actual integrity counts and preserves open gates", () => {
    render(<Phase18ResearchSection envelope={savedEnvelope()} onOpenPhase={vi.fn()} />);
    expect(screen.getByTestId("phase18-workbench")).toBeVisible();
    expect(screen.getByText("182 / 182")).toBeVisible();
    expect(screen.getByText("26 / 26")).toBeVisible();
    expect(screen.getByText("Phase 7 历史证据缺失")).toBeVisible();
    expect(screen.getByText("真实硬件在环验证未执行")).toBeVisible();
    expect(screen.getByText(/工作区有跨阶段未提交变更/)).toBeVisible();
  });

  it("opens the selected historical evidence without changing its source", () => {
    const onOpenPhase = vi.fn();
    render(<Phase18ResearchSection envelope={savedEnvelope()} onOpenPhase={onOpenPhase} />);
    fireEvent.click(screen.getByRole("button", { name: "打开事件驱动自愈证据" }));
    expect(onOpenPhase).toHaveBeenCalledWith("phase9");
  });

  it("shows a no-data state when the audit summary has no finding records", () => {
    const incomplete = savedEnvelope();
    incomplete.artifact = { competition_readiness: { status: "NOT_ASSESSABLE" }, research_findings: [], phase_statuses: [], delivery_gates: [], test_matrix: [] };
    incomplete.supporting_artifacts = {};
    render(<Phase18ResearchSection envelope={incomplete} onOpenPhase={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("没有可核验的结果摘要");
    expect(screen.getByText("本地 RC 文件记录")).toBeVisible();
  });
});
