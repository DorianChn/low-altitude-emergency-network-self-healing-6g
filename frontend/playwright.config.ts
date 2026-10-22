import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig } from "@playwright/test";

const projectRoot = resolve(import.meta.dirname, "..");
const frontendRoot = resolve(import.meta.dirname);
const runtimePython = resolve(projectRoot, ".runtime/venv/Scripts/python.exe");
const runtimeNode = resolve(projectRoot, ".runtime/tools/node-v24.19.0-win-x64/node.exe");
const chromePath = "C:/Program Files/Google/Chrome/Application/chrome.exe";
const edgePath = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const executablePath = process.env.PHASE6_BROWSER_EXECUTABLE
  ?? (existsSync(chromePath) ? chromePath : edgePath);

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results/phase6",
  fullyParallel: true,
  workers: process.env.CI ? 1 : 4,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  expect: { timeout: 12_000 },
  reporter: [["list"], ["html", { outputFolder: "./playwright-report/phase6", open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:5197",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: { executablePath },
  },
  webServer: [
    {
      command: existsSync(runtimePython)
        ? `"${runtimePython}" -m uvicorn lowalt6g.phase6_api:app --host 127.0.0.1 --port 8137`
        : "uv run --frozen --offline uvicorn lowalt6g.phase6_api:app --host 127.0.0.1 --port 8137",
      cwd: projectRoot,
      url: "http://127.0.0.1:8137/api/demo/phase6",
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: existsSync(runtimeNode)
        ? `"${runtimeNode}" "${resolve(frontendRoot, "node_modules/vite/bin/vite.js")}" --host 127.0.0.1 --port 5197 --strictPort`
        : "npm run dev -- --host 127.0.0.1 --port 5197 --strictPort",
      cwd: frontendRoot,
      url: "http://127.0.0.1:5197/",
      reuseExistingServer: false,
      timeout: 60_000,
      env: { LOWALT6G_API_TARGET: "http://127.0.0.1:8137" },
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
