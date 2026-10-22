import { appendFile } from "node:fs/promises";
import { chromium } from "playwright";

const origin = process.env.SOAK_ORIGIN ?? "http://127.0.0.1:15197";
const durationMs = Number(process.env.SOAK_DURATION_MS ?? 1_800_000);
const started = Date.now();
const scenarios = ["severe_persistent_faults", "dynamic_failures", "high_mobility_rescue", "high_load_backhaul_limit"];
const output = new URL("../delivery/soak-progress.jsonl", import.meta.url);
const errors = [];
const samples = [];
const browser = await chromium.launch({ headless: true, executablePath: process.env.PERF_BROWSER || undefined });
const context = await browser.newContext({ viewport: { width: 1366, height: 768 } });
const page = await context.newPage();
let apiResponses = 0;
page.on("pageerror", (error) => errors.push({ type: "pageerror", message: error.message, at_ms: Date.now() - started }));
page.on("console", (message) => { if (message.type() === "error") errors.push({ type: "console", message: message.text(), at_ms: Date.now() - started }); });
page.on("requestfailed", (request) => { const message = request.failure()?.errorText; if (message !== "net::ERR_ABORTED") errors.push({ type: "requestfailed", url: request.url(), message, at_ms: Date.now() - started }); });
page.on("response", (response) => { if (new URL(response.url()).pathname.startsWith("/api/")) { apiResponses++; if (!response.ok()) errors.push({ type: "api", status: response.status(), url: response.url(), at_ms: Date.now() - started }); } });
let cycle = 0;
let currentScenario = "severe_persistent_faults";
let nextSample = 60_000;
try {
  await page.goto(`${origin}/demo`, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: /灾害网络自愈/ }).waitFor({ timeout: 15000 });
  while (Date.now() - started < durationMs) {
    let scenario = scenarios[(cycle + 1) % scenarios.length];
    if (scenario === currentScenario) scenario = scenarios[(scenarios.indexOf(currentScenario) + 1) % scenarios.length];
    const responsePromise = page.waitForResponse((response) => new URL(response.url()).pathname === `/api/demo/phase6/${scenario}` && response.ok(), { timeout: 15000 });
    await page.getByRole("combobox", { name: "切换灾害场景" }).selectOption(scenario);
    const response = await responsePromise;
    const payload = await response.json();
    await page.waitForFunction((seed) => document.querySelector(".phase6-range-heading small")?.textContent?.includes(`seed ${seed} `), payload.seed);
    currentScenario = scenario;
    if ((cycle % 3) === 2) {
      await page.goto(`${origin}/research`, { waitUntil: "domcontentloaded" });
      await page.getByRole("heading", { name: "策略结构与适用边界" }).waitFor({ timeout: 15000 });
      await page.goto(`${origin}/demo`, { waitUntil: "domcontentloaded" });
      await page.getByRole("heading", { name: /灾害网络自愈/ }).waitFor({ timeout: 15000 });
      currentScenario = "severe_persistent_faults";
    }
    cycle++;
    const elapsed = Date.now() - started;
    if (elapsed >= nextSample) {
      const heap = await page.evaluate(() => performance.memory?.usedJSHeapSize ?? null).catch(() => null);
      const sample = { elapsed_ms: elapsed, cycles: cycle, api_responses: apiResponses, js_heap_bytes: heap, errors: errors.length, route: new URL(page.url()).pathname };
      samples.push(sample);
      await appendFile(output, `${JSON.stringify(sample)}\n`);
      console.log(JSON.stringify(sample));
      nextSample += 60_000;
    }
    await page.waitForTimeout(1000);
  }
} catch (error) {
  errors.push({ type: "fatal", message: error?.stack ?? String(error), at_ms: Date.now() - started });
} finally {
  const result = { origin, duration_ms: Date.now() - started, cycles: cycle, api_responses: apiResponses, errors, samples };
  await appendFile(output, `${JSON.stringify({ final: result })}\n`);
  await context.close();
  await browser.close();
  console.log(JSON.stringify({ final: true, duration_ms: result.duration_ms, cycles: cycle, api_responses: apiResponses, error_count: errors.length }));
  if (result.duration_ms < durationMs || errors.length) process.exitCode = 1;
}



