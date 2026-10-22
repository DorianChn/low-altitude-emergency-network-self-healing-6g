import fs from "node:fs/promises";
import { pathToFileURL } from "node:url";

const baseURL = process.env.DEMO_BASE_URL;
const outputDir = process.env.DEMO_VIDEO_RAW_DIR;
const planPath = process.env.DEMO_VIDEO_PLAN;
const browserPath = process.env.BROWSER_EXE;
const playwrightEntry = process.env.PLAYWRIGHT_ENTRY;
const reportPath = process.env.DEMO_VIDEO_REPORT;
if (!baseURL || !outputDir || !planPath || !browserPath || !playwrightEntry || !reportPath) {
  throw new Error("Set DEMO_BASE_URL, DEMO_VIDEO_RAW_DIR, DEMO_VIDEO_PLAN, BROWSER_EXE, PLAYWRIGHT_ENTRY, and DEMO_VIDEO_REPORT.");
}

const plan = JSON.parse(await fs.readFile(planPath, "utf8"));
const { chromium } = await import(pathToFileURL(playwrightEntry).href);
const viewport = { width: 1920, height: 1080 };
await fs.mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ headless: true, executablePath: browserPath });
const context = await browser.newContext({ viewport, deviceScaleFactor: 1, recordVideo: { dir: outputDir, size: viewport } });
const page = await context.newPage();
const errors = [];
let currentRoute = null;
page.on("pageerror", error => errors.push(error.message));
page.on("console", message => { if (message.type() === "error") errors.push(message.text()); });

async function setCaption(text) {
  await page.evaluate(caption => {
    let host = document.getElementById("phase18-recording-caption");
    if (!host) {
      host = document.createElement("div");
      host.id = "phase18-recording-caption";
      Object.assign(host.style, {
        position: "fixed", left: "50%", bottom: "20px", transform: "translateX(-50%)",
        zIndex: "2147483647", maxWidth: "calc(100vw - 64px)", padding: "14px 24px",
        border: "1px solid rgba(232, 94, 54, .42)", borderRadius: "3px",
        background: "rgba(11, 12, 14, .90)", color: "#f4efe8",
        font: "600 22px/1.35 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif",
        letterSpacing: ".025em", boxShadow: "0 8px 30px rgba(0,0,0,.28)",
        backdropFilter: "blur(8px)", textAlign: "center", pointerEvents: "none"
      });
      document.body.appendChild(host);
    }
    host.textContent = caption;
  }, text);
}

async function gotoRoute(route) {
  if (route === currentRoute) return;
  if (currentRoute === null) {
    await page.goto(new URL(route, baseURL).toString(), { waitUntil: "domcontentloaded" });
  } else {
    const navigation = page.locator(`.main-nav a[href="${route}"]`);
    await navigation.click();
  }
  await page.locator("main").first().waitFor({ state: "visible" });
  currentRoute = route;
}

const browserStarted = Date.now();
for (const segment of plan.segments) {
  await gotoRoute(segment.route);
  if (segment.scenario && segment.scenario !== "severe_persistent_faults") {
    await page.getByLabel("切换灾害场景").selectOption(segment.scenario);
    await page.getByRole("heading", { name: /严重持续故障|动态故障|高移动救援|高负载 \/ 回传受限/ }).waitFor({ state: "visible" });
    await page.waitForTimeout(500);
  }
  if (segment.strategy) {
    await page.getByTestId(`strategy-${segment.strategy}`).click();
  }
  if (segment.seek_seconds !== undefined) {
    const slider = page.getByRole("slider", { name: "灾害网络回放时间" });
    await slider.focus();
    for (let i = 0; i < 27; i += 1) await page.keyboard.press("ArrowRight");
    const play = page.getByRole("button", { name: "继续回放" });
    if (await play.isVisible()) await play.click();
    await page.waitForTimeout(1200);
    const pause = page.getByRole("button", { name: "暂停回放" });
    if (await pause.isVisible()) await pause.click();
  }
  if (segment.scroll_y !== undefined) await page.evaluate(y => window.scrollTo({ top: y, behavior: "instant" }), segment.scroll_y);
  await setCaption(segment.caption);
  await page.waitForTimeout(Number(segment.target_seconds) * 1000);
}

const video = page.video();
await context.close();
const rawVideoPath = await video.path();
await browser.close();
const stat = await fs.stat(rawVideoPath);
const result = {
  status: errors.length ? "FAIL" : "PASS",
  capture: "Playwright browser video from the local React app and FastAPI saved replay service",
  base_url: baseURL,
  viewport,
  segment_count: plan.segments.length,
  planned_content_seconds: plan.segments.reduce((sum, segment) => sum + Number(segment.target_seconds), 0),
  recorded_file_bytes: stat.size,
  raw_video_path: rawVideoPath,
  browser_errors: errors,
  wall_clock_seconds: Number(((Date.now() - browserStarted) / 1000).toFixed(2)),
};
await fs.writeFile(reportPath, JSON.stringify(result, null, 2) + "\n", "utf8");
console.log(JSON.stringify(result, null, 2));
if (errors.length) process.exitCode = 1;
