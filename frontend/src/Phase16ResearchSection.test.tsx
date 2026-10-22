import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Phase16ResearchSection } from "./Phase16ResearchSection";
import type { ResearchArtifactEnvelope } from "./research-model";

const envelope: ResearchArtifactEnvelope = {
  schema_version: "1.0",
  dataset_id: "phase16",
  artifact_path: "results/phase16_measurement_readiness.json",
  artifact_sha256: "a".repeat(64),
  experiment_role: "current_measurement_readiness_snapshot",
  model_scope: "measurement_readiness_and_uncertainty_framework_not_field_calibration",
  artifact: {
    status: "NOT_READY_FOR_FIELD_MEASUREMENT",
    field_measurement_executed: false,
    equipment_readiness_checklist: [{ item: "授权接收机和证书", status: "MISSING" }],
    measurement_adapters: [
      { id: "offline_file_import", status: "IMPLEMENTED_AND_TESTED", live_device: false },
      { id: "radio_instrument_driver", status: "UNAVAILABLE", live_device: false },
      { id: "future_instrument_adapter_contract", status: "INTERFACE_ONLY", live_device: false },
    ],
    measurement_plan: {
      status: "PLANNED_NOT_EXECUTED",
      scenarios: [{ id: "urban_street", purpose: "街道传播重复性" }],
    },
  },
  supporting_artifacts: {
    environment_inventory: { artifact_path: "results/phase16_environment_inventory.json", artifact_sha256: "b".repeat(64), artifact: {
      equipment_scan: { status: "COMPLETED", matched_devices: [], serial_port_count: 0 },
      available_measurement_data: { dataset_id: "mendeley_8p6r8ft4fz_v2", record_count: 1370, source_file_count: 14, carrier_frequency_hz: 3600000000 },
    } },
    measurement_import: { artifact_path: "results/phase16/imports/public.audit.json", artifact_sha256: "c".repeat(64), artifact: {
      import_status: "PASS", missing_device_metadata: ["device_model", "calibration_status"], required_device_metadata_fields: ["device_model", "calibration_status"],
      record_count_before_cleaning: 1370, record_count_after_cleaning: 1370, rejected_record_count: 0, duplicate_record_count: 0,
      source_sha256: "d".repeat(64), source_hash_unchanged_after_read: true, cleaned_output_sha256: "e".repeat(64),
    } },
    uncertainty_budget: { artifact_path: "results/phase16_uncertainty_budget.json", artifact_sha256: "f".repeat(64), artifact: {
      combined_standard_uncertainty_db: null, sources: [{ id: "rx_power", category: "instrument", unit: "dB", standard_uncertainty: null }],
    } },
    calibration_state: { artifact_path: "results/phase16_calibration_state.json", artifact_sha256: "1".repeat(64), artifact: {
      status: "NOT_CALIBRATED", state_transitions: [],
    } },
    integrity_audit: { artifact_path: "results/phase16_integrity_audit.json", artifact_sha256: "2".repeat(64), artifact: {
      status: "PASS", protected_hashes: [{ matches: true }], raw_dataset_files: [{ matches: true }],
    } },
  },
};

describe("Phase16ResearchSection", () => {
  it("renders persisted evidence and keeps unavailable measurement distinct from software validation", () => {
    render(<Phase16ResearchSection envelope={envelope} />);

    expect(screen.getByText("真实设备校准尚未完成；当前工具用于测量准备、数据审计和校准验收。")).toBeVisible();
    expect(screen.getByText("1,370 条 · 14 个源文件")).toBeVisible();
    expect(screen.getByText("0 / 2 项")).toBeVisible();
    expect(screen.getByText("已实现并测试")).toBeVisible();
    expect(screen.getByText("不可用")).toBeVisible();
    expect(screen.getByText("仅接口约定")).toBeVisible();
    expect(screen.getByText("城市街道")).toBeVisible();
    expect(screen.getByText("计划场景 · 尚未测量")).toBeVisible();
    expect(screen.getByText("不可计算")).toBeVisible();
    const scan = screen.getByLabelText("已核验数据");
    expect(within(scan).getByText("未发现已枚举的测量仪器")).toBeVisible();
  });
});
