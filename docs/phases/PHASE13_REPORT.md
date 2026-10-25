# Phase 13 Report — Digital Twin Interaction and Research Visualization

## Result

Phase 13 adds a research evidence route and event detail to the existing React application. Existing routes `/`, `/command`, `/decision`, `/lab`, and `/demo` remain registered. The research page reads saved Phase 5/8/9/10/11 experiment summaries through a read-only, allowlisted API. The Phase 6 replay remains discrete and precomputed; no experiment JSON values or frozen manifests were rewritten.

## Implemented

- `/research` stage and scene selection for Phase 5, 8, 9, 10, and 11.
- An accessible mean-and-interval rescue-service plot whose strategy rows select the paired comparison; Phase 8 mechanism variants can be toggled.
- Paired same-seed comparison, recovery success/failure counts and times, conditional latency/P95 and sample count, energy, available energy-per-rescue-service measure, compute time, strategy mechanism metadata, source file and SHA-256.
- A new `GET /api/research/{phase_id}` read-only endpoint integrated into the same FastAPI app used by the Phase 6 launcher. Unsupported IDs return 404; missing or invalid files return 503.
- `/demo` event detail for the selected recorded event. A before/after summary is rendered only when exact adjacent saved frames exist; otherwise the page explains why no delta is shown. The explanation does not infer event-level causality.
- An explicit statement that Phase 10/11 contain multi-UAV aggregates but no API-verified multi-UAV frame replay.
- Missing API data uses an explicit error state; no placeholder or interpolated experiment values are supplied.
- New API schema, data-lineage and visualization-design documents; a repeatable audit script; component and browser tests.

## Data sources and interpretation

| Phase | Summary file | Saved sample/run scope |
| --- | --- | --- |
| 5 | `results/phase5_validation_summary.json` | 4 scenes, 20 held-out seeds per scene, 400 policy runs |
| 8 | `results/phase8_replication_summary.json` | 80 seed rows, 1,360 policy/variant runs |
| 9 | `results/phase9_corrected_confirmation_summary.json` | 80 seed rows, 480 policy runs |
| 10 | `results/phase10_confirmation_summary.json` | 80 seed rows, 400 policy runs |
| 11 | `results/phase11_confirmation_summary.json` | 80 seed rows, 880 policy runs |

The new page does not pool phases or recompute saved inferential results. Recovery counts keep failures in the denominator; successful-only and horizon-censored descriptive times are separate. Latency is conditional on successful user-time samples, displays its sample count, and is not characterized as a paired effect when strategy sample sets differ. Phase 9's saved E comparison identifier is mapped to the UI's stable E policy ID.

The Phase 6 replay files retain their manifest-selected seeds 7000/7020/7040/7060, five single-UAV policies per scene, and 61 saved frames at 10-second intervals across 600 seconds. Phase 10/11 multi-UAV statistics are not represented as per-frame fleet motion.

## Validation

- Full Python regression: **68 passed in 41.18 s**; it includes the seven Phase 13 API contract cases. The focused API contract run also passed **7/7**.
- Frontend unit tests: **9 passed**.
- Frontend lint: **passed**.
- Production build: **passed**. Output: initial JS 416.00 kB (134.13 kB gzip), research route 33.83 kB (10.27 kB gzip), ECharts chunk 533.66 kB (180.42 kB gzip). The ECharts chunk remains lazy-loaded but still triggers Vite's 500 kB advisory.
- Playwright: **15 of 15 passed in 14.3 s** after limiting parallel workers to four and making research tests navigate directly to the research page. The suite checks four scenario replays, Phase 8/9/11 data selection, missing-data handling, timeline controls, all five previous routes plus `/research`, no browser errors during route traversal, no horizontal overflow, and screenshots at 1920×1080, 1366×768, and 390×844.
- Frozen data and browser-evidence audit: **PASS**, 32 historical result artifact hashes checked against Phase 9/10/11 manifests; 4 Phase 6 scenario files each contain five policies × 61 frames with scenario and seed matching the manifest; API/frontend route inventories pass; all six PNG screenshots exist and have the expected viewport widths.
- The research API JSON Schema file parses successfully.

The first Playwright attempt used 14 workers and overloaded the local replay/API path; ten tests timed out while still displaying the initial loading state. Reducing parallelism to four and removing the unnecessary demo load before research-page tests resolved the infrastructure contention. One later E2E assertion targeted an internal Phase 8 ID not exposed as the accessible chart label; it was corrected to use the public human-readable label. The final run covered all 15 tests.

## Screenshots

Generated from the running browser against the local FastAPI and Vite services:

- `artifacts/phase13/browser/demo-1920x1080.png`
- `artifacts/phase13/browser/demo-1366x768.png`
- `artifacts/phase13/browser/research-1920x1080.png`
- `artifacts/phase13/browser/research-1366x768.png`
- `artifacts/phase13/browser/research-390x844.png`
- `artifacts/phase13/browser/research-phase9-1920x1080.png` (shows the saved negative E−B′ paired result)

The E2E assertions confirmed no document-width overflow at all three specified research viewports and both desktop demo viewports. Browser route coverage includes all five existing routes and the new research route. Demo runtime console/page errors are checked; route traversal also checks console errors.

## Historical integrity and Git

Working branch: `phase13-scientific-visualization`. At the start of Phase 13 the repository already contained extensive mixed uncommitted Phase 1–12 material. Those changes were preserved. No broad staging, reset, commit, or remote push was performed. The frozen result audit passes; Phase 13 adds only its own audit JSON and code/docs, without changing the earlier experiment files.

## Limits

- Phase 10/11 have summary aggregates but no verified per-tick multi-UAV replay; no fleet trajectory or link state is drawn for those phases.
- The page can show only statistics present in each phase's summary schema. It cannot reconstruct individual-run decision histories or missing raw distributions.
- C/D/E/F/G/H/I/J remain rule-based or deterministic optimization implementations, not trained machine-learning models.
- The urban network, delay, coverage, and energy remain abstract simulation quantities, not real radio, UAV, or 6G field measurements.
- ECharts remains a 533.66 kB lazy chunk and Vite continues to report a size advisory. The new route itself is separately lazy-loaded and does not import ECharts.
- Full Python regression completed: 68 tests passed in 41.18 seconds.

## Run locally

From the project directory, start the existing offline demo launcher:

```powershell
./scripts/start_demo.ps1
```

Open `http://127.0.0.1:5173/research` for the research evidence workbench, or use the app navigation's **研究证据** item. The launcher uses the existing offline FastAPI/React startup path and pre-generated data; the research route does not require running experiments.

For checks and integrity audit:

```powershell
uv run --offline pytest -q
cd frontend
npm test -- --run
npm run lint
npm run build
npm run test:e2e
cd ..
uv run --offline python scripts/phase13_visualization_audit.py
```
