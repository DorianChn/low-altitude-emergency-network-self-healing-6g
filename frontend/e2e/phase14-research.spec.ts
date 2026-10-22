import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { expect, test } from "@playwright/test";

test("Phase 14 model evidence loads saved values and stays usable at three widths", async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  const failedApiResponses: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("response", (response) => {
    if (response.url().includes("/api/research/phase14") && response.status() >= 400) {
      failedApiResponses.push(`${response.status()} ${response.url()}`);
    }
  });

  await page.goto("/research");
  await expect(page.getByRole("heading", { name: /把每个结论/ })).toBeVisible();
  await page.getByRole("tab", { name: /Phase 14/ }).click();
  await expect(page.getByRole("heading", { name: "链路预算如何改变服务判断" })).toBeVisible();
  await expect(page.getByText("20 个确认种子")).toBeVisible();
  await expect(page.getByTestId("phase14-research")).toBeVisible();

  const scene = page.getByRole("combobox", { name: "选择灾害场景" });
  await scene.selectOption("severe_persistent_faults");
  await expect(page.locator(".radio-validation-head p")).toContainText("严重持续故障");
  await page.setViewportSize({ width: 1920, height: 1080 });
  const desktopScreenshot = testInfo.outputPath("phase14-research-1920x1080.png");
  mkdirSync(dirname(desktopScreenshot), { recursive: true });
  await page.screenshot({ path: desktopScreenshot, fullPage: true, animations: "disabled" });

  await scene.selectOption("dynamic_failures");
  await page.setViewportSize({ width: 1366, height: 768 });
  const laptopScreenshot = testInfo.outputPath("phase14-research-1366x768.png");
  await page.screenshot({ path: laptopScreenshot, fullPage: true, animations: "disabled" });

  await scene.selectOption("high_mobility_rescue");
  await page.setViewportSize({ width: 390, height: 844 });
  const mobileScreenshot = testInfo.outputPath("phase14-research-390x844.png");
  await page.screenshot({ path: mobileScreenshot, fullPage: true, animations: "disabled" });
  const widths = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  expect(widths.document).toBeLessThanOrEqual(widths.viewport);
  expect(widths.body).toBeLessThanOrEqual(widths.viewport);
  expect(pageErrors).toEqual([]);
  expect(failedApiResponses).toEqual([]);
});
