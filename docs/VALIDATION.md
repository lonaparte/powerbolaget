# Powerbolaget 0.0.1 validation records

Release verification date: 2026-10-12. Current checks ran on Linux with Python 3.12 and OpenDSSDirect.py 0.9.4. Exact dependency pins are in `requirements.lock`.

## Current release checks

- All 43 model/API tests passed in 7.99 seconds. One existing Starlette/AnyIO `BlockingPortal` deprecation warning remains.
- JavaScript syntax checks passed for `web/app.js` and `web/planner.js`; Python compilation passed for `app/`, `tests/` and `tools/`.
- The health endpoint and API metadata report version 0.0.1. Climate metadata identifies the setting as an unnamed Baltic coastal city.
- Chromium checked the overview, climate, model guide, saves, electrical diagram, standard construction, custom planner parameters and schedule, approved custom construction, protection confirmation and timeline, turbine details, reload persistence and a 390 px mobile viewport.
- All inspected views used English, including dynamic SVG text, backend messages and the construction schedule. An old browser language preference did not change the interface after reload. The language switch has been removed.
- The browser created Baltic One with four turbines, a 110 m hub on T01, a ring wiring template and 2 MW / 8 MWh additional storage. Validation produced a 138-day schedule and CNY 167,145,417 investment. Draft saving and construction approval succeeded; reload preserved the approved project.
- Browser checks reported no console errors or warnings, and no horizontal page overflow at desktop or mobile sizes. Current screenshots are `screenshots/01-overview-en.jpg`, `02-planner-en.jpg` and `03-climate-en.jpg`.

Raw current evidence is in `results/pytest.txt`, `results/browser-validation.json` and `results/rename-validation.json`.

## Automated model coverage

`tests/test_planning_climate.py` uses three seeds and every day boundary plus two-hour noise knots throughout a year (13,179 boundary times). Values on each side of a 10⁻⁷-day offset check continuity of wind, temperature, clouds, waves, irradiance, daylight and circular wind direction. Tests also cover annual/monthly periodic functions, winter/summer day length, zero nighttime irradiance, daily integration, seeded repeatability and shared construction weather.

Plans reject manually supplied construction duration, invalid IDs, nonfinite values, missing endpoints, disconnected approved graphs, undersized unit transformers and inconsistent storage power/energy. Disconnected drafts may be saved. Scheduling tests compare resources, turbine sizes and forced weather delay, checking dependencies and critical paths.

Commissioning tests check frozen plans, no new generation before the commissioning boundary, equipment insertion at that boundary, 66 kV topology, per-unit parameters, actual cable and transformer results, minimum-SOC precharge conservation and turbine maintenance. API tests check validation without state mutation, rejected stale revisions, checkpoints and export/import replay consistency.

## Retained annual simulation evidence

The numerical model and climate coefficients are unchanged by this English-language release. The retained annual run was recorded on 2026-10-11 on Windows with Python 3.12; it was not rerun for this release. `tests/endurance.py` calculated all 35,040 intervals from the initial state with seed 42, including the three standard expansion projects and their calculated commissioning schedules.

| Metric | Recorded model result |
|---|---:|
| City demand / served energy | 88,706.13 / 88,706.13 MWh |
| Unserved energy | 0.00 MWh |
| Wind generation | 63,467.17 MWh |
| Direct wind share | 61.11% |
| Grid imports, including precharge | 35,458.63 MWh |
| Grid exports | 7,435.63 MWh |
| Curtailment | 8,227.67 MWh |
| SOC range | 22.5%–90.0% |
| Maximum equipment loading | 88.137% |
| Maximum power-balance residual | 0.0514 kW |
| Annual energy residual | 0.04620 MWh |

The minimum SOC fraction includes capacity dilution when new batteries commission at minimum SOC; the 15% physical limit was respected. Wind directly supplied about 61% of served energy, with the external grid covering substantial low-wind deficits. This does not establish year-round independent wind supply. Raw annual evidence remains in `results/annual-validation.json` and `results/annual-replay.json`.

## Retained historical commissioning example

Earlier browser acceptance used Baltic One with a freely added T02→T04 ring cable rated at 500 A, T01 hub height 110 m and 2 MW / 8 MWh storage. It calculated 138 days, roughly CNY 166.8 million, commissioning on 2030-05-19 00:00 CET and 21 vessel-hours of weather waiting. Advancing all intervals through day 140 confirmed 40 MW total wind capacity and 8 MW / 32 MWh storage, with original custom topology and turbine outputs shown in the operating view. The replay is retained in `examples/baltic-one-day-140.json`. The current browser test uses an automatic ring template, so its cable lengths and cost differ from that historical example.

## Model and release limits

Construction quantities, vessel productivity, manufacturing lead times, wave proxies and costs are not site-calibrated. Custom rings lack full directional protection coordination and N-1 design; power-flow previews cover the current condition only. Protection uses discrete events rather than electromagnetic transients. City load is a demonstration district and weather is synthetic. See [MODEL.md](MODEL.md).

The source release includes the complete MIT `LICENSE`, original copyright, third-party notices and license texts. Development documentation and tools use English. Historical screenshots that contained the previous language or named location have been replaced by current English captures. The clean packaging tool produces `Powerbolaget-0.0.1/` without Git metadata, runtime saves, caches or third-party binaries.

## Docker deployment verification (2026-10-12)

The repository now includes a portable `Dockerfile`, `compose.yaml` and `.dockerignore`. Docker Engine on Linux builds the same Linux image used by Docker Desktop on macOS and Windows. The image runs as UID 10001, exposes container port 8082, and uses one application worker with `/data` backed by a named save volume.

An actual Linux/amd64 build installed the pinned dependencies successfully and passed `pip check`. Compose configuration validation passed. The documented disposable-container test command passed all 43 model/API tests in 12.60 seconds, with the existing Starlette/AnyIO deprecation warning.

The Compose service became healthy with a host-port override of 8094. HTTP checks verified the English page, version 0.0.1 health response, native OpenDSS plan validation, four simulation intervals, a checkpoint and replay export. After `docker compose down` followed by container recreation using the same volume, the browser session retained its step, revision, metrics and checkpoint. The temporary verification containers and volume were removed afterward.

Raw Docker evidence is in `results/docker-validation.json` and `results/docker-pytest.txt`. macOS and Windows were not separately tested; their documented path uses Docker Desktop with Linux containers. Packaging includes the Docker deployment files.

## Linux runtime cleanup verification (2026-10-12)

The native Windows launcher has been removed from the source tree and source packaging. Runtime initialization now rejects non-Linux hosts with an English instruction to use Linux containers. Windows runs the application through Docker Desktop. Platform-neutral system and monospace fonts replace Windows-specific frontend fonts.

The dependency lock was regenerated on Linux. It contains 26 runtime/test packages and excludes colorama, which pytest requires only on native Windows. The other package versions remain unchanged. Original third-party license texts and historical audit evidence remain preserved.

The rebuilt Linux image passed all 43 model/API tests in 13.68 seconds, with the existing Starlette/AnyIO warning. Desktop overview, planner and climate views, plus mobile overview and planner views at 390 px, passed browser checks with no console errors or horizontal page overflow. Simulated non-Linux platform imports verified the native runtime restriction. Packaging was checked for the absence of Windows launch scripts.

Raw evidence is in `results/linux-validation.json` and `results/linux-pytest.txt`.
