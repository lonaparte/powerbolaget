# Powerbolaget 0.1.0 — model description

This document maps the implementation to the *Powerbolaget game design and simulation specification v0.2*, section by section. Each item is marked:
- **Implemented**: as the spec describes it.
- **Simplified**: implemented in a reduced form; the reduction is stated.
- **Deferred**: not in 0.1.0.

Every coefficient that is not a measurement is an assumption. They are collected in `app/params.py` (economy, society, tariffs, costs) and in the module that uses them (fault rates in `app/energy.py`, load shapes in `app/loads.py`).

## 0. Decisions

| Spec 0.1 | Status |
|---|---|
| 1. Open-ended, no score or win condition | Implemented. The UI reports states, trends and causes only. |
| 2. Player is Powerbolaget, with full authority over energy assets; firms and residents decide for themselves | Implemented. Commands cover only Powerbolaget's assets (build, maintenance, switching, batteries, link margin). The HVAC interconnector is built by the grid operator, not the player. |
| 3. A fictional world close to Gotland | Implemented. Gutnö's coastline is traced from Gotland. Population follows Gotland's pattern: about half in and around a main town on the west coast, the rest mostly in small coastal towns. Firms, wiring and settings are invented. |
| 4. Energy, Economic Production and Society models on one World Simulation Core, plus a Load Profile Engine | Implemented: `world.py`, `energy.py` and `grid.py`, `economy.py`, `society.py`, `loads.py`. |
| 5. Layered event coupling, POP state with probabilistic transitions, bounded-rational firms | Implemented. |
| 6. About 20 zones; at most 10,000 POP objects | 18 zones, dense where people are dense. About 190 POPs; the cap is enforced (`society.check_cap`). |
| 7. Society and economy hourly and daily, slow variables monthly; grid every minute; events at their own timestamps | Implemented. Transient-stability windows are deferred (see 6.2). |
| 8. Every turbine is its own device with a real collector connection | Implemented. Each turbine has its own 0.69 kV bus, unit transformer and collector cable. |
| 9. Hourly plans never step the load; real switching is not smoothed | Implemented; tested in `tests/test_world.py`. |
| 10. No speed target; measure first | Measured: about 125 ms per simulated hour on one core of a 2.1 GHz Xeon server (`results/benchmark-365d.json`). |
| 11. Three views with layers, inspector and pinned objects | Implemented, in an HTML client (see 10.1). |
| 12. Free investment with full bookkeeping; reference-price tariffs | Implemented. Shortfalls are booked as external financing. |

The game starts on 1 January, year 1 of the **Fantasy Era** (幻想纪元). The calendar has 365-day years and fixed local time UTC+1 with no daylight saving (`app/calendar.py`).

## 1. World

- **Geography** (`app/island.py`). Coordinates are in km, converted from longitude and latitude at 57.5° N. The coastline is anchored at Hoburgen, the Burgsvik bay, Näsudden, Ronehamn, Ljugarn, Östergarn, Slite, Fårösund, Hallshuk, Visby and Klintehamn, plus a separate islet like Fårö. Land area is about 3,400 km².
- **Zones.** 18 economic zones, each defined as the land nearest its centre:
  - seven in and around Västerhamn (old town, harbour, east, Gråbo, south, north, hinterland), between 6 and 162 km² each;
  - eleven covering the countryside, between 120 and 570 km² each.
- **Towns.** Each zone has a main settlement drawn at real scale. Examples: Västerhamn Innerstad 4,200, Kalkudden (Slite) 1,500, Strandvik (Klintehamn) 1,500, Hemby (Hemse) 1,900, Romsta (Roma) 900.
- **Land** (`app/land.py`). 0.5 km parcels: sea, shore, town, village, farmland, forest, limestone heath, wetland, quarry and nature reserve. Land use is world data, not decoration:
  - the map draws it;
  - turbine siting obeys it (no turbines in towns, villages, quarries, reserves or on the shore, and at least 500 m from homes);
  - wind roughness depends on it;
  - parcel population estimates spread each zone's residents by settlement weight.
- **Mainland boundary.** Goods trade at mainland reference prices plus or minus freight. Visitors and immigrants come from the mainland. Electricity flows over the links at a reference price (`World.energy_price`).

## 2. Architecture and ownership

| State | Owner | Where |
|---|---|---|
| POPs, household money | Society | `world.pops`, ledger accounts `pop:<id>` |
| Firms, stock, plans, investment | Economy | `world.firms`, `world.markets`, `world.jobs` |
| Buses, branches, turbines, storage, links | Energy | `world.grid` (data), `grid.Network` (compiled solver, never saved) |
| Load devices, trajectories, thermal states | Load engine | `world.devices` |
| Time, events, random state, ledger, projects, history | World core | `world.py`, `events.py`, `rng.py`, `ledger.py` |

Solvers only read a snapshot and return results (`app/solvers/`).

Ids: `zone_id` z01–z18, `pop_id` `<zone>_<group>`, `firm_id`, `equipment_id` `<firm>_<key>`, `bus_id`, `branch_id`. A zone maps to buses through its 20 kV feeder bus; firms connect to their own bus (the cement works to `ind_kal`).

## 3. Layered event coupling

The minute loop in `World.advance` follows spec 3.2:
1. Integrate the interval just ended from the last solved state, at constant power between solves.
2. On boundaries, settle the completed hour, day and month (production, bills, markets, wages, demography, investment). Only then do the society and economy plan the next period from what is known, using forecasts rather than the future.
3. Requests, then dispatch, then AC power flow, then protection.
4. Queued events inside the minute are handled at their own timestamps: integrate up to the event, apply it, solve again.

Ordering and safety:
- Protection actions sort before restorations, equipment commands, commissioning and economic events at the same instant.
- Event ids never repeat, so a reloaded save cannot run an event twice.
- A tripped machine stays down until its restart delay has passed, whatever the plan says.

Messages: firm and society plans (spec: ActivityPlan) become device targets and equipment events. Device requests per minute are the spec's DemandTrajectory. Served energy per device and hour is the PhysicalResult. Hourly bills and output settlement are the EconomicSettlement. Request, served and billed energy are separate fields.

## 4. Society

- **POPs.** Residents by zone and group: industry, agriculture, hospitality, services, public, construction, retired, youth. Working groups track employed and inactive people separately. Visitors, holiday-home users and seasonal workers are POPs too. Money sits in ledger accounts; moving people take their share of it with them.
- **Daily.**
  - Pensions, child and unemployment benefits from the region, and family support from working adults to the zone's children.
  - Necessities first: housing (part spent locally on construction), off-island spending and food. Then discretionary local services, scaled by income, wealth and price elasticity.
  - Rural residents make shopping trips to the main town.
- **Tourism.** Arrivals depend on season, weekday, forecast weather and lodging price, limited by free beds and ferry seats. Stays average 3.6 days. Holiday-home occupancy follows season and weekends. Visitors are funded from the mainland and their unspent money returns there.
- **Monthly.**
  - Births and deaths by group.
  - Ageing: school leavers join the labour force in the sector with most vacancies nearby; workers retire.
  - Migration: movers are drawn from the unemployed, from a small share of the employed, and from residents pushed by outages. They then choose by logit among zones with free housing and the mainland. Utility covers nearby vacancies, amenity, housing tightness and outage hours.
  - Immigration responds to vacancies and unemployment.
  - The monthly account `end = start + births - deaths + in - out` is exact (`world.demography`).
- **Simplified:** no age-specific fertility, no household formation model, and no explicit commuting matrix. Jobs are matched within 40 km.

## 5. Economy

- **Firms.** Large industry is modelled individually:
  - a cement works with kiln, raw mills, cement mills and auxiliaries;
  - two limestone quarries;
  - a dairy, a feed mill, a slaughterhouse and a brewery;
  - a ferry terminal with shore power on the sailing schedule;
  - a hospital and a construction firm.

  Services, public services, hospitality and agriculture are aggregated per zone. A data centre may come by itself when power is cheap and reliable.
- **Hourly planning.** Each firm decides which machines run in the coming hour from its stock, its targets and the electricity price, and issues start and stop events at staggered minutes. For example, the cement mills run on cheap hours while the silos have room, which is load shifting.
- **Production.** Output is settled from what the equipment actually did:
  - equipment that tripped produced nothing while it was down;
  - the kiln restarts through an eight-hour warm-up at 35 % power;
  - services output follows staff present and served power.
- **Markets.**
  - Island markets for traded goods: local sellers first, the rest imported at import parity. Prices move between export and import parity with scarcity.
  - Exporters ship stock above target, within ship capacity.
  - Local services, lodging and ferry trips clear against each firm's daily capacity; unmet demand is recorded.
- **Labour.** Monthly hiring of unemployed people of the same sector within commuting distance, with limited retraining, and gradual layoffs. Hospitality hires seasonal workers in summer.
- **Investment.** Expansion requires four months of high utilisation and margin; cutting capacity requires eight months of losses. Each decision is followed by a cooldown (hysteresis). Expansions are construction projects paid monthly.
- **Money.** A double-entry ledger in which every payment has a payer and a payee, so the sum of all accounts stays zero (tested). Exports, imports, visitors, immigration, state grants and financing pass through `external` and `financing`.
- **Electricity bills.** Hourly, from served energy:
  - households: last month's reference price plus retail margin and network fee;
  - businesses: the same price with the business network fee;
  - industry: an annual contract price.
- **Simplified:** no credit market and no explicit firm balance sheets beyond cash. Price adjustment is a bounded tatonnement.

## 6. Energy

- **Network.**
  - 110 kV ring between eight substations; 110/20 kV units with on-load tap changers; 20 kV feeders to every zone (a sea cable to the Fårö-like islet).
  - Three wind farms, each with a 110/33 kV farm substation and 33 kV collector strings.
  - The existing HVDC: two links of 130 MW.
  - The planned HVAC: two 220 kV subsea cables, a 220/110 kV transformer at Stenkumla, and 110 kV connections to the link station and Romsta.
- **Power flow.** OpenDSS through OpenDSSDirect.py (DSS-Extensions), every simulated minute, constant-PQ loads and generators.
  - Branches are switched by opening their terminals. Disabling an element leaves buses with no admittance to ground, and OpenDSS then reports a converged but meaningless solution; `tests/test_solvers.py` guards against this.
  - A solution must pass a plausibility check, otherwise it is retried once from a freshly built circuit. If that also fails, it is reported as a numerical failure and the last valid state is kept.
- **Wind.** Power curves with air density, cut-out with hysteresis, and icing stops. Hub wind uses the seasonal shear from the 10 m and 50 m climatology, site exposure and land roughness. Wakes inside each farm use the Jensen (Park) model with root-sum-square superposition. FLORIS is not used (see Deferred).
- **Dispatch** (automatic operator):
  - the mainland exchange stays within link ratings and a margin;
  - batteries shave import peaks, absorb surplus wind and follow price, keeping a reserve if grid-forming;
  - wind is curtailed proportionally;
  - load is shed by priority class: flexible, commercial, residential, industry, critical.
- **Interconnectors.** Before the HVAC link, the HVDC converter is the voltage reference.
  - From 1 Sep FE 6, the mainland AC grid becomes the reference and the HVDC runs as a scheduled injection, carrying its share of the exchange.
  - HVAC capacity is staged: 150 MW, then 300 MW from 1 Mar FE 7, then 440 MW from FE 9.
  - Sources: Svenska kraftnät's decision for two 220 kV AC cables Misterhult–Stenkumla, in service 2031, and a 2022 planning figure of 440 MW. The staging is an assumption.
  - If the AC link is lost, the HVDC forms the island again. If every link is lost, a grid-forming battery forms the island while its energy lasts; without one, the island blacks out.
- **Protection.** Faults are sampled hourly:
  - rates per 100 km for lines and per unit otherwise;
  - overhead lines are scaled by storm, lightning and icing; turbines by age and time since maintenance;
  - 75 % of 110 kV overhead-line faults are transient and auto-reclose after one second. Permanent faults wait for repair (log-uniform repair times by component);
  - a fault study records the three-phase fault current;
  - thermal overload protection uses inverse time, and the operator recloses after 30 minutes;
  - turbines disconnect outside 0.85–1.12 pu and restart eight minutes after their bus is live again.
- **Deferred:** RMS or EMT dynamics (ANDES), frequency response, unbalanced faults, a PyPSA unit-commitment layer, and FLORIS. The spec asks that each be validated before use; the engine contract in `app/solvers` is where a dynamic backend would plug in.

## 7. Load Profile Engine

- **Aggregated devices:** households, shops and services, public services, lodging, farms. Their drivers change at most hourly: occupied households, staff, guests, herd.
- **Ramps.** Each hourly plan anchors at the value requested now and ramps linearly to the next target, so a new plan never causes a step. Spec 7.2.1 is respected: hourly energy is not claimed to be preserved by interpolation.
- **Shapes.** Time-of-day shapes are smooth periodic functions; rest days and holidays use their own shapes.
- **Heating.** Each zone has a single-node thermal model: an indoor temperature with a setback schedule, heat-pump COP depending on outdoor temperature, and electric shares of direct heating and heat pumps. Outages cool homes, and reconnection produces cold-load pickup.
- **Equipment.** State machines (off, starting, running, stopping, tripped, warm-up). Starts and stops are events at their own times.
- **Mapping.** Each device is attached to one bus. The zone and firm ids show who pays and who is affected.

## 8. Interfaces

The HTTP API (`app/main.py`) is the boundary between client and core:

| Endpoint | Purpose |
|---|---|
| `POST /api/session` | Start a game |
| `POST /api/session/load` | Load a game from a save |
| `POST /api/tick` | Advance the clock and return the snapshot |
| `POST /api/command` | Apply a player command |
| `POST /api/preview` | Check, price and connect a planned build |
| `POST /api/save` | Return the full state |
| `POST /api/entity` | Inspector details |
| `POST /api/parcel` | Parcel details |
| `POST /api/table` | Statistics pages |
| `GET /api/land` | The parcel grid |

POST requests need the `X-PowerGame` header and a same-origin `Origin`, and are limited to 12 MB.

## 9. UI

Three views (island, grid, economy), map layers, a context inspector, parcel details, build mode with previews, a dock (balance charts, events, projects, pinned objects) and a day/night theme. Information comes in layers: the overview first, then the selected object, then its composition and history.

## 10. Deployment, saves, performance

- **10.1 Client.** The spec proposes a Godot 4 web client. 0.1.0 uses an HTML/JavaScript client so the game runs anywhere without a build step. The core does not depend on the client, as the spec requires, so a Godot client can replace it later.
- **10.2 Performance.** See `docs/VALIDATION.md`. No acceleration target is set.
- **10.3 Saves.** A save holds:
  - versions and the complete world (zones, POPs, firms, stocks, money, devices with trajectory anchors and thermal states);
  - the grid with every switch, tap, state of charge and repair;
  - projects, the event queue, partial-hour accumulators and every random stream's state.

  Saves live in the player's browser and are validated on load. Continuing a loaded save matches an uninterrupted run within floating-point tolerance: the power-flow engine restarts from a flat start, about 1e-7 relative (`tests/test_world.py`).
- **10.4 Data.** Climate comes from NASA POWER 2001–2025 at 57.5° N, 18.5° E (`app/island-climatology.json`, with its source and period). Everything else is synthetic. No real facility coordinates, topology or protection settings are reproduced.

## 12. Open questions carried forward

Calibrated economic coefficients, tariff pass-through, the turbine dynamic model, HVAC and HVDC control choices, construction costs and durations, and load calibration against public annual statistics are all open. UI usability with students is still to be tested.
