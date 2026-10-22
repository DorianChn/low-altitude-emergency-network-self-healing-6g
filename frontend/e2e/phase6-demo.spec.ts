import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

const SCENARIOS = [
  { id: "severe_persistent_faults", title: "严重持续故障", seed: 7000 },
  { id: "dynamic_failures", title: "动态故障", seed: 7020 },
  { id: "high_mobility_rescue", title: "高移动救援", seed: 7040 },
  { id: "high_load_backhaul_limit", title: "高负载 / 回传受限", seed: 7060 },
] as const;

async function openDemo(page: import("@playwright/test").Page) {
  await page.goto("/demo");
  await expect(page.getByRole("heading", { name: /灾害网络自愈.*演示台/ })).toBeVisible();
}

for (const scenario of SCENARIOS) {
  test(`loads the recorded ${scenario.title} validation replay`, async ({ page }) => {
    await openDemo(page);
    if (scenario.id !== "severe_persistent_faults") {
      await page.getByLabel("切换灾害场景").selectOption(scenario.id);
    }
    const artifactResponse = await page.request.get(`/api/demo/phase6/${scenario.id}`);
    expect(artifactResponse.ok()).toBeTruthy();
    const artifact = await artifactResponse.json();

    await expect(page.getByRole("heading", { name: scenario.title, level: 2 })).toBeVisible();
    await expect(page.getByText(`本次轨迹 seed ${scenario.seed}`)).toBeVisible();
    expect(artifact.seed).toBe(scenario.seed);
    expect(artifact.live_stream).toBe(false);
    expect(Object.keys(artifact.strategies)).toHaveLength(5);
    for (const run of Object.values(artifact.strategies) as Array<{ state_snapshots: unknown[] }>) {
      expect(run.state_snapshots).toHaveLength(61);
    }
  });
}

test("keeps A/B/B′/C/D controls, timeline, and displayed experiment values consistent", async ({ page }) => {
  await openDemo(page);
  const response = await page.request.get("/api/demo/phase6/severe_persistent_faults");
  const artifact = await response.json();
  const rescueMean = artifact.strategy_aggregates.C_rolling_horizon_mpc.metrics.rescue_user_service_success_rate.mean;
  const expectedRescueMean = `${(rescueMean * 100).toFixed(2)}%`;
  const rollingRow = page.getByRole("row").filter({ hasText: "滚动时域优化" });
  await expect(rollingRow).toContainText(expectedRescueMean);

  for (const id of [
    "A_no_recovery",
    "B_phase1_static_grid",
    "Bprime_static_grid_shared_safety",
    "C_rolling_horizon_mpc",
    "D_lexicographic_rescue_priority",
  ]) {
    await expect(page.getByTestId(`strategy-${id}`)).toBeVisible();
  }

  await page.getByTestId("strategy-D_lexicographic_rescue_priority").click();
  await expect(page.getByTestId("strategy-D_lexicographic_rescue_priority")).toHaveAttribute("aria-pressed", "true");

  const slider = page.getByRole("slider", { name: "灾害网络回放时间" });
  await slider.focus();
  for (let index = 0; index < 27; index += 1) await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("img", { name: /种子 7000 的仿真网络状态，时间 04:30/ })).toBeVisible();

  await page.getByRole("button", { name: "继续回放" }).click();
  await expect(page.getByRole("button", { name: "暂停回放" })).toBeVisible();
  await expect(page.getByRole("img", { name: /种子 7000 的仿真网络状态，时间 04:40/ })).toBeVisible({ timeout: 3000 });
  await page.getByRole("button", { name: "暂停回放" }).click();
  await expect(page.getByRole("button", { name: "继续回放" })).toBeVisible();
});

for (const viewport of [
  { name: "1920x1080", width: 1920, height: 1080 },
  { name: "1366x768", width: 1366, height: 768 },
  { name: "390x844", width: 390, height: 844 },
]) {
  test(`renders without page overflow at ${viewport.name}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("/demo");
    await expect(page.getByRole("heading", { name: /灾害网络自愈.*演示台/ })).toBeVisible();
    await expect(page.getByTestId("strategy-C_rolling_horizon_mpc")).toBeVisible();
    const dimensions = await page.evaluate(() => ({
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: window.innerWidth,
      tableClientWidth: document.querySelector<HTMLElement>(".phase6-table-scroll")?.clientWidth ?? 0,
      tableScrollWidth: document.querySelector<HTMLElement>(".phase6-table-scroll")?.scrollWidth ?? 0,
    }));
    expect(dimensions.documentWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
    if (viewport.width === 390) expect(dimensions.tableScrollWidth).toBeGreaterThan(dimensions.tableClientWidth);
    const screenshotPath = testInfo.outputPath(`demo-${viewport.name}.png`);
    mkdirSync(dirname(screenshotPath), { recursive: true });
    await page.screenshot({ path: screenshotPath, fullPage: true });
  });
}

test("research workbench keeps stage, scene, strategy, and source selection in one dataset", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.goto("/research");
  await expect(page.getByRole("heading", { name: "策略结构与适用边界" })).toBeVisible();
  await expect(page.getByText("results/phase11_confirmation_summary.json").first()).toBeVisible();
  await expect(page.getByText(/多无人机逐帧回放不可用/)).toBeVisible();

  const phase11 = await page.request.get("/api/research/phase11");
  const phase11Envelope = await phase11.json();
  const expected = `${(phase11Envelope.artifact.scenarios.dynamic_failures.policies.G_centralized_coordination_uav3.metrics.rescue_user_service_success_rate.mean * 100).toFixed(2)}%`;
  await expect(page.getByRole("button", { name: /G · 三机集中协同/ })).toContainText(expected);

  await page.getByRole("tab", { name: /Phase 8/ }).click();
  await expect(page.getByText("results/phase8_replication_summary.json").first()).toBeVisible();
  await page.getByLabel("显示 C/D 机制变体").check();
  const phase8 = await page.request.get("/api/research/phase8");
  const phase8Envelope = await phase8.json();
  const expectedVariant = `${(phase8Envelope.artifact.scenarios.dynamic_failures.all_strategy_and_variant_summaries.D_rescue_priority_off.metrics.rescue_user_service_success_rate.mean * 100).toFixed(2)}%`;
  await expect(page.getByRole("button", { name: /D rescue priority off/ })).toContainText(expectedVariant);

  await page.getByRole("tab", { name: /Phase 9/ }).click();
  await expect(page.getByText("results/phase9_corrected_confirmation_summary.json").first()).toBeVisible();
  await expect(page.getByText("−7.05 pp")).toBeVisible();
  const screenshotPath = testInfo.outputPath("research-phase9-1920x1080.png");
  mkdirSync(dirname(screenshotPath), { recursive: true });
  await page.screenshot({ path: screenshotPath, fullPage: true });
});

test("preserves the five existing routes and the new research route", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  const routes = [
    ["/", "总览"],
    ["/command", "数字孪生"],
    ["/decision", "自愈决策"],
    ["/lab", "实验室"],
    ["/demo", "现场演示"],
    ["/research", "研究证据"],
  ] as const;
  for (const [path, label] of routes) {
    await page.goto(path);
    await expect(page.locator(".main-nav .active")).toHaveText(label);
    await expect(page.locator("main").first()).toBeVisible();
  }
  expect(errors).toEqual([]);
});

for (const viewport of [
  { name: "1920x1080", width: 1920, height: 1080 },
  { name: "1366x768", width: 1366, height: 768 },
  { name: "390x844", width: 390, height: 844 },
]) {
  test(`research workbench fits ${viewport.name} and exposes readable evidence`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("/research");
    await expect(page.getByRole("heading", { name: "救援服务率" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "恢复结局与删失时间" })).toBeVisible();
    const dimensions = await page.evaluate(() => ({ documentWidth: document.documentElement.scrollWidth, viewportWidth: window.innerWidth }));
    expect(dimensions.documentWidth).toBeLessThanOrEqual(dimensions.viewportWidth);
    const screenshotPath = testInfo.outputPath(`research-${viewport.name}.png`);
    mkdirSync(dirname(screenshotPath), { recursive: true });
    await page.screenshot({ path: screenshotPath, fullPage: true });
  });
}

for (const width of [320, 375, 414]) {
  test(`primary navigation labels remain single-line at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 });
    await page.goto("/");
    const audit = await page.evaluate(() => {
      const links = [...document.querySelectorAll<HTMLElement>(".main-nav .nav-link")];
      return {
        labels: links.map((link) => {
          const range = document.createRange();
          range.selectNodeContents(link);
          const rect = link.getBoundingClientRect();
          const navRect = link.parentElement!.getBoundingClientRect();
          return {
            label: link.textContent?.trim() ?? "",
            lineCount: range.getClientRects().length,
            fullyVisible: rect.left >= navRect.left && rect.right <= navRect.right,
          };
        }),
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth,
        navWidth: (document.querySelector(".main-nav") as HTMLElement).clientWidth,
        navScrollWidth: (document.querySelector(".main-nav") as HTMLElement).scrollWidth,
      };
    });
    expect(audit.labels).toHaveLength(6);
    expect(audit.labels.every((item) => item.lineCount === 1)).toBeTruthy();
    expect(audit.labels.every((item) => item.fullyVisible)).toBeTruthy();
    expect(audit.navScrollWidth).toBeLessThanOrEqual(audit.navWidth);
    expect(audit.documentWidth).toBeLessThanOrEqual(audit.viewportWidth);
  });
}

test("research workbench reports missing summaries without fallback values", async ({ page }) => {
  await page.route("**/api/research/phase11", (route) => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ detail: "summary artifact unavailable" }),
  }));
  await page.goto("/research");
  await expect(page.getByRole("alert")).toContainText("summary artifact unavailable");
  await expect(page.getByRole("button", { name: "重新读取" })).toBeVisible();
});

test("reports a missing replay instead of substituting animated placeholder data", async ({ page }) => {
  await openDemo(page);
  await page.route("**/api/demo/phase6/dynamic_failures", (route) => route.fulfill({
    status: 503,
    contentType: "application/json",
    body: JSON.stringify({ detail: "Demo artifact is unavailable: phase6_demo_dynamic_failures.json" }),
  }));
  await page.getByLabel("切换灾害场景").selectOption("dynamic_failures");
  await expect(page.getByRole("alert")).toContainText("Demo artifact is unavailable");
  await expect(page.getByRole("button", { name: "重新读取数据" })).toBeVisible();
});

test("emits no browser runtime errors on the phase-six demo page", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await openDemo(page);
  await expect(page.getByRole("heading", { name: "严重持续故障", level: 2 })).toBeVisible();
  expect(errors).toEqual([]);
});

test("keeps Phase 6 page context and data independent from historical replay requests", async ({ page }) => {
  const apiPaths: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/")) apiPaths.push(path);
  });
  await openDemo(page);
  await expect(page.getByTestId("current-page-context")).toContainText("seed 7000");
  expect(apiPaths).toContain("/api/demo/phase6");
  expect(apiPaths).toContain("/api/demo/phase6/severe_persistent_faults");
  expect(apiPaths.some((path) => ["/api/health", "/api/replay/2026", "/api/experiments/phase2", "/api/experiments/phase5"].includes(path))).toBeFalsy();
});

test("preserves unknown events at the same timestamp and stops event navigation at boundaries", async ({ page }) => {
  await page.route("**/api/demo/phase6/severe_persistent_faults", async (route) => {
    const response = await route.fetch();
    const artifact = await response.json();
    artifact.environment_events.push(
      { time_s: 0, event_type: "aaa_unknown_event", target_id: "unknown-alpha", reason: "synthetic test record" },
      { time_s: 0, event_type: "aab_unknown_event", target_id: "unknown-beta", reason: "synthetic test record" },
    );
    await route.fulfill({ response, json: artifact });
  });
  await openDemo(page);
  const previous = page.getByRole("button", { name: "上一个关键事件" });
  const next = page.getByRole("button", { name: "下一个关键事件" });
  await expect(previous).toBeDisabled();
  await page.getByRole("button", { name: "查看全部事件" }).click();
  const alphaRow = page.locator(".phase6-event-row").filter({ hasText: "unknown-alpha" });
  const betaRow = page.locator(".phase6-event-row").filter({ hasText: "unknown-beta" });
  await expect(alphaRow).toHaveCount(1);
  await expect(betaRow).toHaveCount(1);
  await alphaRow.click();
  await expect(page.locator(".phase6-event-evidence pre")).toContainText("unknown-alpha");
  const slider = page.getByRole("slider", { name: "灾害网络回放时间" });
  await slider.focus();
  await page.keyboard.press("End");
  await expect(next).toBeDisabled();
});

test("shows a truthful empty state when a replay has no events", async ({ page }) => {
  await page.route("**/api/demo/phase6/severe_persistent_faults", async (route) => {
    const response = await route.fetch();
    const artifact = await response.json();
    artifact.environment_events = [];
    for (const strategy of Object.values(artifact.strategies) as Array<{ event_log: unknown[] }>) strategy.event_log = [];
    for (const station of artifact.strategies.A_no_recovery.state_snapshots[0].stations) station.healthy = true;
    await route.fulfill({ response, json: artifact });
  });
  await openDemo(page);
  await page.getByRole("button", { name: "查看全部事件" }).click();
  await expect(page.getByText("当前场景尚无可显示事件。")).toBeVisible();
});
test("a late scenario response cannot replace the latest selected replay", async ({ page }) => {
  await openDemo(page);
  await page.route("**/api/demo/phase6/dynamic_failures", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 1200));
    await route.continue().catch(() => {});
  });
  const delayedRequest = page.waitForRequest((request) => new URL(request.url()).pathname === "/api/demo/phase6/dynamic_failures");
  const selector = page.getByLabel("切换灾害场景");
  await selector.selectOption("dynamic_failures");
  await delayedRequest;
  await selector.selectOption("high_mobility_rescue");
  await expect(page.getByTestId("current-page-context")).toContainText("seed 7040");
  await page.waitForTimeout(1400);
  await expect(page.getByTestId("current-page-context")).toContainText("seed 7040");
  await expect(page.getByRole("heading", { name: "高移动救援" })).toBeVisible();
});
test("shows the research page's multi-seed source without loading historical replay data", async ({ page }) => {
  const apiPaths: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/")) apiPaths.push(path);
  });
  await page.goto("/research");
  await expect(page.getByRole("heading", { name: "策略结构与适用边界" })).toBeVisible();
  await expect(page.getByTestId("current-page-context")).toContainText("多种子汇总");
  expect(apiPaths).toContain("/api/research/phase11");
  expect(apiPaths.some((path) => ["/api/health", "/api/replay/2026", "/api/experiments/phase2", "/api/experiments/phase5"].includes(path))).toBeFalsy();
});

test("space and arrow shortcuts control only the page-owned replay", async ({ page }) => {
  await openDemo(page);
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("slider", { name: "灾害网络回放时间" })).toHaveValue("10");
  await page.keyboard.press("Space");
  await expect(page.getByRole("button", { name: "暂停回放" })).toBeVisible();
  await page.getByRole("link", { name: "研究证据" }).click();
  await expect(page.getByRole("heading", { name: "策略结构与适用边界" })).toBeVisible();
  await page.keyboard.press("Space");
  await expect(page.getByRole("button", { name: "暂停回放" })).toHaveCount(0);
});

test("exposes a first-use guide, all-event filter, and metric definitions", async ({ page }) => {
  await openDemo(page);
  await page.getByText("首次使用：三步看懂这次回放").click();
  await expect(page.getByText(/先选灾害场景/)).toBeVisible();
  await page.getByRole("button", { name: "查看全部事件" }).click();
  await expect(page.getByRole("button", { name: "仅看关键事件" })).toBeVisible();
  await page.getByText("指标与分母说明").click();
  await expect(page.getByText(/不是“每种子 P95 的均值”/)).toBeVisible();
});

test("playback rate advances stored frames and switching scene resets the clock", async ({ page }) => {
  await openDemo(page);
  await page.getByLabel("回放速度").selectOption("2");
  await page.getByRole("button", { name: "继续回放" }).click();
  await expect(page.getByRole("slider", { name: "灾害网络回放时间" })).toHaveValue("10", { timeout: 3000 });
  await page.getByRole("button", { name: "暂停回放" }).click();
  await page.getByLabel("切换灾害场景").selectOption("dynamic_failures");
  await expect(page.getByTestId("current-replay-seed")).toContainText("seed 7020");
  await expect(page.getByRole("slider", { name: "灾害网络回放时间" })).toHaveValue("0");
});

test("reduced-motion preference and keyboard focus remain usable", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openDemo(page);
  await page.keyboard.press("Tab");
  const focus = await page.evaluate(() => ({
    tag: document.activeElement?.tagName,
    visible: Boolean(document.activeElement && (document.activeElement as HTMLElement).getClientRects().length),
    reducedMotion: matchMedia("(prefers-reduced-motion: reduce)").matches,
  }));
  expect(focus.visible).toBeTruthy();
  expect(focus.reducedMotion).toBeTruthy();
});
