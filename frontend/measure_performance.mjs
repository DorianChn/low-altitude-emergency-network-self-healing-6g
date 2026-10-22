import { chromium } from "playwright";

const origin = process.env.PERF_ORIGIN ?? "http://127.0.0.1:15197";
const scenarios = [
  ["severe_persistent_faults", "严重持续故障"],
  ["dynamic_failures", "动态故障"],
  ["high_mobility_rescue", "高移动救援"],
  ["high_load_backhaul_limit", "高负载 / 回传受限"],
];
const browser = await chromium.launch({ headless: true, executablePath: process.env.PERF_BROWSER || undefined });
const rows = [];
try {
  for (let sample = 1; sample <= 3; sample++) {
    const context = await browser.newContext({ viewport: { width: 1366, height: 900 } });
    const page = await context.newPage();
    const requests = [];
    const errors = [];
    page.on("response", (response) => {
      if (response.url().includes("/api/")) requests.push({
        url: new URL(response.url()).pathname,
        status: response.status(),
        duration_ms: null,
        bytes: Number(response.headers()["content-length"] ?? 0),
      });
    });
    page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
    page.on("console", (message) => { if (message.type() === "error") errors.push(`console: ${message.text()}`); });
    const start = performance.now();
    const response = await page.goto(`${origin}/demo`, { waitUntil: "domcontentloaded" });
    try {
      await page.getByRole("heading", { name: /灾害网络自愈/ }).waitFor({ timeout: 8000 });
    } catch (error) {
      await page.screenshot({ path: "../delivery/performance-cold-failure.png", fullPage: true }).catch(() => {});
      console.error(JSON.stringify({ body: await page.locator("body").innerText().catch(() => ""), errors, api: requests }, null, 2));
      throw error;
    }
    await page.locator(".phase6-range-heading small").waitFor();
    await page.locator(".panel-live-meta").waitFor();
    await page.getByRole("slider", { name: "灾害网络回放时间" }).waitFor();
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const readyMs = performance.now() - start;
    const browserMetrics = await page.evaluate(() => ({
      jsHeapUsedBytes: performance.memory?.usedJSHeapSize ?? null,
      jsHeapLimitBytes: performance.memory?.jsHeapSizeLimit ?? null,
      viewport: `${innerWidth}x${innerHeight}`,
    }));
    const resources = await page.evaluate(() => performance.getEntriesByType("resource").map((item) => ({
      name: new URL(item.name).pathname,
      duration_ms: Number(item.duration.toFixed(2)),
      transfer_bytes: item.transferSize ?? null,
      decoded_bytes: item.decodedBodySize ?? null,
    })));
    rows.push({ kind: "cold_navigation", sample, status: response?.status(), ready_ms: Number(readyMs.toFixed(2)), api: requests.slice(), browser: { ...browserMetrics, playwrightNodeRssBytes: process.memoryUsage().rss }, resources });

    const select = page.getByRole("combobox", { name: "切换灾害场景" });
    let cycle = 0;
    for (const [target, label] of scenarios) {
      for (let repetition = 0; repetition < 10; repetition++) {
        const from = scenarios[(scenarios.findIndex(([slug]) => slug === target) + 1) % scenarios.length][0];
        const fromResponse = page.waitForResponse((res) => new URL(res.url()).pathname === `/api/demo/phase6/${from}` && res.ok());
        await select.selectOption(from);
        const fromPayload = await (await fromResponse).json();
        await page.waitForFunction((seed) => document.querySelector(".phase6-range-heading small")?.textContent?.includes(`seed ${seed} `), fromPayload.seed);
        const startSwitch = performance.now();
        const nextResponse = page.waitForResponse((res) => new URL(res.url()).pathname === `/api/demo/phase6/${target}` && res.ok());
        await select.selectOption(target);
        const apiResponse = await nextResponse;
        const payload = await apiResponse.json();
        await page.waitForFunction((seed) => document.querySelector(".phase6-range-heading small")?.textContent?.includes(`seed ${seed} `), payload.seed);
        await page.locator(".panel-live-meta").waitFor();
        const elapsed = performance.now() - startSwitch;
        const apiDuration = await page.evaluate((path) => {
          const entries = performance.getEntriesByType("resource").filter((item) => new URL(item.name).pathname === path);
          return entries.length ? Number(entries.at(-1).duration.toFixed(2)) : null;
        }, `/api/demo/phase6/${target}`);
        rows.push({ kind: "hot_scene_switch", scenario: target, label, repetition: ++cycle, elapsed_ms: Number(elapsed.toFixed(2)), api_resource_duration_ms: apiDuration, post_response_parse_and_render_ms: apiDuration === null ? null : Number(Math.max(0, elapsed - apiDuration).toFixed(2)), api_status: apiResponse.status(), response_bytes: Number(apiResponse.headers()["content-length"] ?? 0), seed: payload.seed });
      }
    }
    await context.close();
  }
} finally {
  await browser.close();
}
console.log(JSON.stringify({ captured_utc: new Date().toISOString(), origin, cold_samples: rows.filter((row) => row.kind === "cold_navigation").length, hot_samples: rows.filter((row) => row.kind === "hot_scene_switch").length, rows }, null, 2));
