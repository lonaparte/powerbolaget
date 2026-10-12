# Powerbolaget 0.0.1

A power-supply and offshore wind-farm planning game set in an unnamed Baltic coastal city. Wind supplies the city, batteries balance energy, and the external grid provides backup. The existing farm has 20 MW of capacity; expand it or plan up to four custom plants.

## Deploy with Docker

Linux is the only supported native runtime. Install Docker Engine and the Docker Compose plugin on Linux. Windows must run Powerbolaget through Docker Desktop with Linux containers; native Windows execution is unsupported. On macOS, use Docker Desktop with Linux containers. The same Compose files run the Python 3.12 application and native OpenDSS dependencies inside a Linux container; no host Python installation is required.

```sh
git clone https://github.com/lonaparte/powerbolaget.git
cd powerbolaget
docker compose up -d --build
```

Open http://127.0.0.1:8082. The service publishes port 8082 on host loopback and runs one application worker. Check startup and logs with:

```sh
docker compose ps
docker compose logs -f game
```

The `saves` named volume stores browser scenarios and checkpoints in `/data/coastal.sqlite3`. It survives container restarts, rebuilds and `docker compose down`. Keep one application instance per save volume. To stop or restart the service:

```sh
docker compose down
docker compose up -d
```

To change the host port, create a `.env` file beside `compose.yaml` containing `POWERBOLAGET_PORT=8083`, then run `docker compose up -d`. The container continues listening on port 8082; open http://127.0.0.1:8083 on the host.

To update the application:

```sh
git pull --ff-only
docker compose up -d --build
```

## Plan, build and operate

1. Select **Plan a wind farm**, enter a turbine count, or add turbines and junctions individually.
2. Select a node to edit its position, rated power, hub height, rotor diameter, power curve and transformer. Select a cable to edit length, R/X/C, ampacity and switch state. Drag nodes and wire freely, or start from radial, star or ring templates. Moving a node preserves cable lengths; **Recalculate lengths** updates them explicitly.
3. Select the substation to configure 35/66 kV collection, the site transformer and additional onshore storage. Configure vessels, engineering and electrical teams, supply lines, water depth and port distance.
4. Select **Validate & schedule**. The system checks connectivity and real OpenDSS AC power flow, then calculates the critical path and commissioning date from quantities, dependencies, resources and hourly weather windows. Construction duration cannot be entered manually.
5. Approve construction when funds are sufficient. Approval freezes the plan and charges its cost. The plant generates no power during construction and joins the network at its calculated commissioning time. Select it in the farm menu to inspect topology, cable loading and turbine output.
6. **Coastal weather** shows wind, temperature, irradiance, daylight and seven days of simulated weather. Continuous functions and smooth seeded disturbances generate conditions; monthly data calibrate coefficients. Weather remains continuous at midnight and is reproducible from the seed.

The application, API messages and development documentation use English. The default four-turbine 5 MW plan, seed 42, January 1 start and default resources produce a 133-day schedule. The reference Baltic One plan adds a ring cable, a 110 m hub and 2 MW / 8 MWh storage and produces a 138-day schedule. Changes to quantities, resources or start date recalculate these results.

Actions autosave. Checkpoints and JSON command replays are supported. A scenario lasts 365 days; projects cannot be approved if they finish after that horizon. Save identifiers and the replay format remain compatible with earlier versions. Old replays use the current weather and scheduling model, so historical numerical results can differ.

## Day and night

The interface uses a pixel-art style with a day and a night palette. In **Auto** mode the theme follows the simulated clock and the coastal climate's sunrise and sunset; the header toggle cycles Auto, Day and Night and is remembered by the browser. The coastal map is drawn as pixel art from the live simulation: rotors turn with turbine output, dots on the cables show power flowing to the substation, city, battery and grid, isolated circuits turn red, the four city districts appear as load zones on their 10 kV feeders and light up at night only where their demand is served, cloud shadows and sea streaks follow the wind, and land is snow-covered below freezing. Select a turbine on the map for details.

## Model scope

This is a reviewable teaching and planning model. OpenDSS constrains currents, losses, voltages and transformer capacity; battery energy is conserved across intervals. NASA POWER 2001–2020 gridded climatology calibrates the Baltic coastal climate functions. City demand represents a demonstration district rather than measured whole-city consumption.

Construction uses an original quantity and critical-path approximation. Productivity, manufacturing lead times, vessel prices and wave relationships are scenario assumptions. ORBIT is a methodological reference, not an imported library. Custom rings participate in power flow, but individual cable directional protection is not implemented. Fault controls target the six original fault locations. Batteries aggregate at the shared onshore bus; grid-following storage does not support independent islanding or black start. See [Model documentation](docs/MODEL.md).

## Validate

Run the Python model and API tests in a disposable container using the same image:

```sh
docker compose run --rm --no-deps game python -m pytest -q -p no:cacheprovider
```

For frontend development, JavaScript syntax checks can be run from a Linux shell with Node.js installed:

```sh
node --check web/app.js
node --check web/planner.js
node --check web/pixel.js
```

The model/API suite covers planning, scheduling, continuous climate, commissioning, protection and save handling. `tests/endurance.py` validates all 35,040 intervals of a simulated year. See [Validation records](docs/VALIDATION.md), raw evidence in `results/`.

## License and release folder

Original project code uses the MIT License. The bitmap display font `web/pixel-font.woff` is original and generated by `tools/pixel_font.py`, which needs fontTools only when regenerating it. The complete root `LICENSE` retains the original copyright. Dependencies retain their own licenses, including the OpenDSSDirect.py Alliance terms and native KLU, Eigen and NumPy components. See `LICENSE-REVIEW.txt`, hashes and provenance in `results/license-inventory.json`, and original texts in `licenses/`.

`DEVELOPMENT-TREE.txt` lists the source release. `tools/package.py --output <new-folder-path>` creates a clean `Powerbolaget-0.0.1/` folder for upload without an archive. The folder includes source, Docker deployment files, documentation, examples, any available screenshots and licenses and excludes Git metadata, saves, backups, virtual environments and third-party binaries.
