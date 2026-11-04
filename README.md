# Powerbolaget 0.1.0

An open regional energy, economy and society simulation. You run **Powerbolaget**, the energy company of **Gutnö**, a fictional island modelled on the scale, climate and economic geography of Gotland. You plan, build and operate the island's grid: wind turbines, batteries, lines and transformers. The rest of the island lives its own life. The weather changes, and residents work, shop, move, are born and die. Visitors come in summer. Firms plan production, hire, invest and sometimes leave, and equipment fails and gets repaired.

There is no win condition and no score. The game reports what happens and why, and you decide what to change.

The game starts on 1 January, year 1 of the **Fantasy Era** (幻想纪元), and starts running as soon as the page opens.

## Run it

With Docker:

```sh
docker compose up -d --build
```

Open http://127.0.0.1:8082. The service publishes port 8082 on host loopback only; to use another host port, create a `.env` file beside `compose.yaml` containing `POWERBOLAGET_PORT=8083`. Stop it with `docker compose down`; update with `git pull --ff-only && docker compose up -d --build`.

Without Docker (Linux, Python 3.12):

```sh
python3.12 -m venv .venv
.venv/bin/python tools/deps.py install
.venv/bin/python run.py
```

Saves live in your browser, not on the server, so restarting or updating the server never loses a game. The page autosaves every 45 seconds and whenever it is hidden. **Save ▾** saves now, exports a save file, loads one and starts a new game with a chosen seed. Save files from 0.0.1 (the coastal-city scenario) belong to a different game and cannot be loaded.

## Playing

The screen has three views of the same world, a context inspector on the right and a dock at the bottom.

- **Island**: the pixel-art map. Land use is drawn from the island's 0.5 km parcels: towns, villages, farmland, forest, limestone heath (alvar), wetland, quarries, nature reserves and shore. You can switch on layers for zone borders, wind, turbine wakes, population, tourism, industry, load density, outages and power lines. Seasons and snow follow the simulation. At night (Night, or the day/night cycle after sunset) towns light up, and a town goes dark where it loses supply. Wind arrows are fixed to the map, longer over open sea and shorter over forest and towns.
- **Grid**: the electrical network on the same map. Buses are coloured by voltage and branches by loading, and moving dots show the power flow. Open or tripped breakers show as red dashes, de-energised areas as grey.
- **Economy**: socio-economic statistics, with pages for overview, regions, POPs, firms, markets, finance and demography.
- **Inspector**: click anything to see its current values, history and causes:
  - a turbine, line, bus, substation, battery or the mainland links;
  - a zone, a firm or a POP;
  - a land parcel: land use, people, the long-term and current wind, the expected yield of each turbine model, distances, and whether and at what cost a turbine may be built there.
- **Build** (island view): wind turbines (PB-2.3, PB-3.6 or PB-5.6), batteries (optionally grid-forming), 110 kV lines and transformer units. Every build shows a server-side preview of cost, construction time and electrical connection. Projects are paid monthly; if Powerbolaget runs out of cash, the shortfall is booked as external financing.
- **Operate**: start and end turbine maintenance, open and close breakers, set battery modes and the link operating margin.
- **Time**: the clock runs by itself. Space pauses. Speeds are 10 simulated minutes, 1 hour, 6 hours or 1 day per second, as fast as the server allows. The dock shows the island balance minute by minute for the last four hours and hour by hour for the last three days, plus events, projects (yours, firms' expansions and the grid operator's) and pinned objects.

The interface has a day and a night palette. It starts in **Day**; the three buttons at the top right switch between Day, Night and a day/night cycle. The cycle follows the sun at the island's latitude: short winter days, long summer evenings and light June nights, with dusk and dawn fading gradually.

## What is simulated

The design is documented in `docs/MODEL.md`, mapped section by section to the v0.2 specification.

- **World core.** One authoritative state, one event clock, a double-entry money ledger and independent random streams. Events have sub-minute timestamps. Hour, day and month boundaries settle the completed period before anyone plans the next.
- **Island.** About 55,000 residents in 18 economic zones, using about 900 GWh of electricity a year with a peak near 180 MW, like Gotland. About 40 % of it goes to the cement works, sized like Gotland's Slite plant. Six wind farms with 158 MW cover about 45 % of the island's use, as on Gotland. Zones are dense where people are dense, with seven in and around the main town of Västerhamn (the Visby counterpart). The countryside forms large zones around small coastal towns and inland service villages.
- **Society.** About 190 POP objects (the cap is 10,000): residents grouped by zone and sector, visitors, holiday-home users and seasonal workers.
  - Daily: incomes, transfers and spending.
  - Tourism: arrivals, stays and departures, limited by beds and ferry seats.
  - Monthly: births, deaths, ageing and logit migration driven by jobs, wages, housing, amenities and outages. The population account balances exactly.
- **Economy.** Firms with bounded rationality:
  - each plans the next hour from its own forecast, stock, inputs, staff and the electricity price;
  - output comes from what its equipment actually did, so a tripped cement kiln needs eight hours to warm up again;
  - island markets clear between mainland import and export prices;
  - a labour market, investment with hysteresis, and new investors (a data centre) who decide by themselves to come.
- **Load Profile Engine.** Continuous minute-level P/Q from hourly plans. Plans ramp from the current value, so the top of the hour never jumps. Zone thermal models produce real cold-load pickup after an outage, and machines are discrete state machines.
- **Energy.**
  - AC power flow every simulated minute in OpenDSS, on the full 220/110/33/20/0.69 kV network, with every turbine and its unit transformer modelled.
  - A wind field from the Global Wind Atlas with smooth random variation, and Jensen wakes inside each wind farm.
  - An automatic operator balances the island with the mainland links, then batteries, then wind curtailment, and last load shedding by priority class.
  - On-load tap changers regulate the 20 kV and 110 kV busbars.
  - Faults depend on weather, age and maintenance. Protection trips, overhead lines reclose, faulted 20 kV feeders are re-fed by switching, and repairs take time. Grid-forming batteries can carry the island when the mainland is lost.
  - A power flow that does not converge is reported as a numerical failure, never as a blackout.
- **Mainland links.**
  - The existing HVDC: two links of 130 MW.
  - The grid operator's planned HVAC link: two 220 kV AC subsea cables to Stenkumla south of the main town, after Svenska kraftnät's Gotland connection plan (in service from 2031, which is FE 6). It starts at 150 MW on 1 Sep FE 6, reaches 300 MW with the second cable on 1 Mar FE 7, and 440 MW in FE 9.
  - With the AC link in service, the island is synchronous with the mainland and the HVDC runs on a schedule. If the AC link is lost, the HVDC converter forms the island grid again.

Weather is continuous and seeded: each natural quantity has an observed mean, and the game adds smooth random variation around it. Seasonal means come from the NASA POWER 2001–2025 climatology at 57.5° N, 18.5° E. Wind variability, calms and the wind rose are fitted to NASA POWER hourly data at the same point, and the daily temperature range follows Visby's averages. Each place's long-term wind at 100 m comes from the Global Wind Atlas (CC BY 4.0) on a 1 km grid, so coasts are windier than the interior. Existing turbines then produce about as much per MW as Gotland's real fleet. All other numbers are assumptions, collected in `app/params.py` and marked as such. Gutnö is not a digital twin: its firms, substations, wiring and settings are invented.

Not modelled in 0.1.0:
- electromechanical and electromagnetic transients, frequency dynamics and unbalanced faults;
- offshore wind;
- a nodal electricity market (tariffs follow a mainland reference price);
- road and ferry traffic beyond ferry seat capacity.

## Architecture

- `app/` is the headless simulation core. It runs in worker processes: OpenDSS contexts work only from the thread that created them. Each worker serves its sessions from its main thread and uses one CPU core. Configure with `POWERBOLAGET_WORKERS` (default 1), `POWERBOLAGET_MAX_SESSIONS` (default 8) and `POWERBOLAGET_IDLE_SECONDS` (default 1800).
- If a worker restarts, browsers reload their saves automatically. Saves are untrusted input: ids, catalog references and sizes are checked before a world is rebuilt.
- `web/` is the client: plain HTML, CSS and JavaScript, with no build step.
- Measured on one core of a 2.1 GHz Xeon server: about 175 ms of computation per simulated hour (about 3 ms per simulated minute, of which about 1.5 ms is the power flow). That is about 4 s per simulated day, or 26 minutes per simulated year. `results/benchmark-365d.json` has the full record of a year run without any player input.

Electrical calculation libraries are imported only in `app/solvers/`, behind one contract (`app/solvers/model.py`). `tests/test_solvers.py` fails if any other module imports one. OpenDSS (through OpenDSSDirect.py) is the default backend; pandapower was evaluated earlier and was about 35 times slower for this use.

## Development

```sh
.venv/bin/python tools/deps.py install      # pinned dependencies, then a test feeder on every solver backend
.venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/python tools/benchmark.py --days 30 --output results/benchmark-30d.json
node --check web/js/*.js
```

Browser tests use Playwright and Chromium against a throwaway local server:

```sh
npm install --no-save --package-lock=false playwright
npx playwright install chromium
POWERBOLAGET_TEST_PYTHON=.venv/bin/python node --test tests/browser_game.cjs
```

The Python suite covers:
- the calendar, random streams, events and ledger;
- conservation of money, people and jobs;
- loads that do not step at hour boundaries;
- power balance and energy bookkeeping every minute;
- outages that trip equipment at once, with warm-up after restoration;
- fault, protection and repair, with faulted 20 kV feeders re-fed by switching;
- islanding on a grid-forming battery, and blackout without one;
- the HVAC link taking over from and failing over to the HVDC;
- determinism, and save/load continuation within tolerance;
- construction rules and save validation;
- the HTTP API;
- the solver contract, including a regression test for OpenDSS branch switching.

The browser suite covers auto-run, every view, parcels and building, reload from the browser save, and the phone layout. Results are recorded in `docs/VALIDATION.md`.

## License and release folder

Original project code uses the MIT License; the complete `LICENSE` retains the original copyright. The bitmap display font `web/pixel-font.woff` is original and generated by `tools/pixel_font.py`. Dependencies keep their own licenses, including the OpenDSSDirect.py Alliance terms and native KLU, Eigen and NumPy components; see `LICENSE-REVIEW.txt`, `THIRD-PARTY-NOTICES.txt`, `results/license-inventory.json` and `licenses/`.

`DEVELOPMENT-TREE.txt` lists the source release. `tools/package.py` creates a clean `Powerbolaget-0.1.0/` folder beside the repository (or the new folder given with `--output`) for upload. It makes no archive and leaves out Git metadata, virtual environments and third-party binaries.
