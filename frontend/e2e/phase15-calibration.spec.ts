import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { dirname } from "node:path";

test("Phase 15 shows saved measurement results at desktop and laptop widths", async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto("/research");
  await page.getByRole("tab", { name: /Phase 15/ }).click();
  await expect(page.getByTestId("phase15-research")).toBeVisible();
  await expect(page.getByRole("heading", { name: "有留出结果；项目设备未校准" })).toBeVisible();
  await expect(page.getByText("1.82 dB")).toBeVisible();
  await expect(page.getByText("NOT_CALIBRATED")).toBeVisible();
  await expect(page.getByText(/NOT_ASSESSABLE_MEASUREMENT_UNCERTAINTY_MISSING/)).toBeVisible();
  await page.getByText("如何读整体 MAE 与配对组差").click();
  await expect(page.getByText(/样本池直接相减为 −5\.37 dB/)).toBeVisible();
  for (const image of await page.getByTestId("phase15-research").locator("img").all()) {
    await expect(image).toBeVisible();
    await expect.poll(() => image.evaluate((element: HTMLImageElement) => element.naturalWidth)).toBeGreaterThan(0);
  }
  const desktopScreenshot = testInfo.outputPath("phase15-1920x1080.png");
  await mkdir(dirname(desktopScreenshot), { recursive: true });
  await page.screenshot({ path: desktopScreenshot, fullPage: true });

  await page.setViewportSize({ width: 1366, height: 768 });
  await expect(page.getByTestId("phase15-research")).toBeVisible();
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", 1366);
  const laptopScreenshot = testInfo.outputPath("phase15-1366x768.png");
  await page.screenshot({ path: laptopScreenshot, fullPage: true });
  expect(pageErrors).toEqual([]);
});

test("Phase 15 fits a narrow mobile viewport without hiding the evidence state", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/research");
  await page.getByRole("tab", { name: /Phase 15/ }).click();
  await expect(page.getByTestId("phase15-research")).toBeVisible();
  await expect(page.getByText("NOT_CALIBRATED")).toBeVisible();
  await expect(page.getByRole("heading", { name: "相同 570 条留出样本的误差对照" })).toBeVisible();
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", 390);
  const screenshotPath = testInfo.outputPath("phase15-390x844.png");
  await mkdir(dirname(screenshotPath), { recursive: true });
  await page.screenshot({ path: screenshotPath, fullPage: true });
});
