import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import { dirname } from "node:path";

test("Phase 16 displays saved measurement readiness evidence at supported viewports", async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto("/research");
  await page.getByRole("tab", { name: /Phase 16/ }).click();
  await expect(page.getByTestId("phase16-readiness")).toBeVisible();
  await expect(page.getByText("真实设备校准尚未完成；当前工具用于测量准备、数据审计和校准验收。")).toBeVisible();
  await expect(page.getByText("1,370 条 · 14 个源文件")).toBeVisible();
  await expect(page.getByText("目标设备校准：NOT_CALIBRATED")).toBeVisible();
  await expect(page.getByText("NOT_READY_FOR_FIELD_MEASUREMENT")).toHaveCount(0);
  const desktopScreenshot = testInfo.outputPath("phase16-1920x1080.png");
  await mkdir(dirname(desktopScreenshot), { recursive: true });
  await page.screenshot({ path: desktopScreenshot, fullPage: true });

  await page.setViewportSize({ width: 1366, height: 768 });
  await expect(page.getByTestId("phase16-readiness")).toBeVisible();
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", 1366);
  const laptopScreenshot = testInfo.outputPath("phase16-1366x768.png");
  await page.screenshot({ path: laptopScreenshot, fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByText("目标设备校准：NOT_CALIBRATED")).toBeVisible();
  await expect(page.locator("body")).toHaveJSProperty("scrollWidth", 390);
  const mobileScreenshot = testInfo.outputPath("phase16-390x844.png");
  await mkdir(dirname(mobileScreenshot), { recursive: true });
  await page.screenshot({ path: mobileScreenshot, fullPage: true });
  expect(pageErrors).toEqual([]);
});
