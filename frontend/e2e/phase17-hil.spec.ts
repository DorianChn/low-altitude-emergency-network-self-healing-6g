import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

async function openPhase17(page: import("@playwright/test").Page) {
  await page.goto("/research");
  await page.getByRole("tab", { name: /Phase 17/ }).click();
  await expect(page.getByTestId("phase17-workbench")).toBeVisible();
}

test("Phase 17 API and saved replay agree with the research view", async ({ page }) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await openPhase17(page);
  const response = await page.request.get("/api/research/phase17");
  expect(response.ok()).toBeTruthy();
  const payload = await response.json();
  const replay = payload.supporting_artifacts.offline_replay_validation.artifact;
  const faults = payload.supporting_artifacts.fault_injection_results.artifact;

  expect(replay.frame_count).toBe(61);
  expect(replay.interpolated_frames).toBe(0);
  expect(faults.passed_count).toBe(21);
  await expect(page.getByText("帧 1 / 61")).toBeVisible();
  await expect(page.getByText("21 / 21")).toBeVisible();
  await page.getByRole("button", { name: "单步前进" }).click();
  await expect(page.getByText("帧 2 / 61")).toBeVisible();
  await page.getByRole("button", { name: "继续回放" }).click();
  await expect(page.getByRole("button", { name: "暂停回放" })).toBeVisible();
  await expect(page.getByText("帧 3 / 61")).toBeVisible({ timeout: 2500 });
  await page.getByRole("button", { name: "暂停回放" }).click();
  await page.getByLabel("选择故障注入案例").selectOption("20");
  await expect(page.getByText("SERVICE_RESTORED_AFTER_BACKHAUL_RECOVERY").first()).toBeVisible();
  await expect(page.getByText("当前仅完成软件闭环与记录回放验证。真实硬件在环测试尚未完成。")).toBeVisible();
  expect(pageErrors).toEqual([]);
});

for (const viewport of [
  { name: "1920x1080", width: 1920, height: 1080 },
  { name: "1366x768", width: 1366, height: 768 },
  { name: "390x844", width: 390, height: 844 },
]) {
  test(`Phase 17 research view fits ${viewport.name}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await openPhase17(page);
    const dimensions = await page.evaluate(() => ({
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
    }));
    expect(dimensions.documentWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
    const screenshotPath = testInfo.outputPath(`phase17-${viewport.name}.png`);
    mkdirSync(dirname(screenshotPath), { recursive: true });
    await page.screenshot({ path: screenshotPath, fullPage: true });
  });
}
