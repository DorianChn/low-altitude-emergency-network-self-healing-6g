# 6G / RESCUE frontend

React, TypeScript, Vite and GSAP client for the low-altitude emergency-network research simulator. The interface reads saved Python simulation frames and experiment JSON through a read-only FastAPI API. It does not control radios or claim real-world 6G measurements.

## Windows one-click run

From the project root, run `prepare_environment.cmd` once while internet access is available. This downloads Node.js and uv archives with SHA-256 checks, prepares Python 3.12 and installs dependencies from `uv.lock` and `package-lock.json`. Then run `start_demo.cmd`. The launcher registers the Phase 6 routes on the combined `lowalt6g.phase6_api:app`, checks the frozen replay contract, chooses free loopback ports, and opens `/demo`. Press Q or Ctrl+C in the launcher window to stop only its child processes. Logs are written to `.runtime/logs/`.

## Manual frontend development

After running `prepare_environment.cmd`, start the combined API from the project root:

```powershell
.runtime\venv\Scripts\python.exe -m uvicorn lowalt6g.phase6_api:app --host 127.0.0.1 --port 8123
```

In a second terminal:

```powershell
Set-Location frontend
$env:LOWALT6G_API_TARGET = "http://127.0.0.1:8123"
..\.runtime\tools\node-v24.19.0-win-x64\node.exe .\node_modules\vite\bin\vite.js --host 127.0.0.1 --port 5173
```

The demo and research routes load only their page-owned artifacts. Historical overview, command, decision and lab routes load the historical replay and benchmark APIs. Missing artifacts are displayed as unavailable; the UI does not substitute sample values.

## Routes and controls

- `/` — historical overview, saved network frame, replay controls and cross-seed comparisons.
- `/command` — network topology, service state, events and historical replay controls.
- `/decision` — saved optimizer decisions, constraints and diagnostics.
- `/lab` — Phase 5 multi-hazard validation and its historical baseline.
- `/demo` — Phase 6 frozen offline replay, four scenarios, five strategies and detailed event trace.
- `/research` — multi-stage research evidence and its source context.

On `/demo`, Space toggles playback and left/right arrows step between saved frames. Inputs, buttons, links, sliders, composition, modifiers and repeated Space keydown are excluded. Playback pauses when the page becomes hidden. At 1×, one saved 10-second simulation frame is shown per real second; this is not real-time network telemetry. Mobile controls remain available during scene scrolling, and the comparison table scrolls within its own region.

## Checks

```powershell
..\.runtime\tools\node-v24.19.0-win-x64\npm.cmd test
..\.runtime\tools\node-v24.19.0-win-x64\npm.cmd run lint
..\.runtime\tools\node-v24.19.0-win-x64\npm.cmd run build
..\.runtime\tools\node-v24.19.0-win-x64\npm.cmd run test:e2e
```

The city twin is a lightweight SVG. Entrance motion respects `prefers-reduced-motion`; no continuously rendered 3D scene is used. See the acceptance report in `../delivery/ACCEPTANCE_REPORT.md`.
