import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

async function openPhase18(page: import("@playwright/test").Page) {
  await page.goto("/research");
  await page.getByRole("tab", { name: /Phase 18/ }).click();
  await expect(page.getByTestId("phase18-workbench")).toBeVisible();
}

test("Phase 18 displays saved audit values and links to source-stage evidence", async ({ page }) => {
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  await openPhase18(page);

  const response = await page.request.get("/api/research/phase18");
  expect(response.ok()).toBeTruthy();
  const payload = await response.json();
  const audit = payload.supporting_artifacts.integrity_audit.artifact;
  const summary = payload.artifact;
  const count = audit.raw_experiment_count_audit.checks.filter((item: { matches: boolean }) => item.matches).length;

  await expect(page.getByText(`${audit.protected_history.matched_file_count} / ${audit.protected_history.protected_file_count}`)).toBeVisible();
  await expect(page.getByText(`${count} / ${audit.raw_experiment_count_audit.checks.length}`)).toBeVisible();
  await expect(page.locator(".phase18-ledger article").nth(2).locator("b")).toHaveText(String(audit.protected_history.phase5_source_snapshot_drift_count));
  await expect(page.getByText("无法判定", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("物理 HIL 尚未执行")).toBeVisible();
  await page.getByText(/展开最终测试矩阵/).click();
  await expect(page.locator(".phase18-test-list > div")).toHaveCount(summary.test_matrix.length);
  const buildCheck = page.locator(".phase18-test-list > div").filter({ hasText: "Frontend TypeScript and production build" });
  await expect(buildCheck.locator("b")).toHaveAttribute("data-tone", "warning");

  await page.getByRole("button", { name: /打开.*事件驱动.*证据/ }).click();
  await expect(page.getByRole("heading", { name: "E · 事件驱动恢复" })).toBeVisible();
  expect(summary.research_findings.length).toBeGreaterThan(0);
  expect(pageErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
});

for (const viewport of [
  { name: "1920x1080", width: 1920, height: 1080 },
  { name: "1366x768", width: 1366, height: 768 },
  { name: "390x844", width: 390, height: 844 },
]) {
  test(`Phase 18 final audit fits ${viewport.name}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await openPhase18(page);
    const dimensions = await page.evaluate(() => ({
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
    }));
    expect(dimensions.documentWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
    const screenshotPath = testInfo.outputPath(`phase18-${viewport.name}.png`);
    mkdirSync(dirname(screenshotPath), { recursive: true });
    await page.screenshot({ path: screenshotPath, fullPage: true });
  });
}
