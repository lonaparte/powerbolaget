# Powerbolaget 0.1.0 — current model

This document describes the code on `codex/development` after the v0.2 design review. The reviewed
decisions below override earlier draft assumptions. Gutnö remains a fictional teaching system: public
data set its scale and climate, while firms, network topology, costs, protection settings and response
parameters are declared assumptions.

## Confirmed first-release rules

1. Normal power flow retains every wind turbine, transformer, cable and device status. Important
   electrical events use an aggregated station/farm positive-sequence RMS model.
2. The synthetic VSC-HVDC can form the island. Once a player-built HVAC link is available, the
   mainland AC system provides the voltage/frequency reference and the HVDC follows a power setpoint.
3. Loss of every mainland link automatically attempts islanding. Qualified grid-forming storage has
   first priority, followed by a running black-start oil unit; capacity, SOC, dynamics and protection
   determine the result. Underfrequency shedding, wind curtailment and staged load restoration are
   physical outcomes. With no qualified source the island is de-energised.
4. Construction previews suggest a connection, route and equipment, but the player can change the
   bus, route, line type, station location and transformer arrangement before committing.
5. The player chooses mainland-link technology, capacity, timing and island landing. Synthetic
   mainland connection envelopes, cost, lead time and engineering feasibility constrain the project.
6. The first-release generation catalogue contains wind and backup fuel-oil generators. Solar, gas
   and other plant types are later extensions.
7. A firm plans against its signed electricity contract. Fixed-price customers do not respond to an
   unrelated hourly reference-price movement; indexed customers respond to the index in their contract.
8. Private firms receive finite credit, pay interest and repay surplus cash. Persistent distress can
   reduce employment and cause an orderly exit. Public budgets and Powerbolaget financing are separate.
9. Activities and equipment schedules create demand. Forecast MWh and integrated delivered MWh are
   separate; the first release has no task system that must consume a fixed energy budget by a deadline.
10. The client is HTML/CSS/JavaScript and the simulation is an independent headless Python core.
11. History is layered: global and object hourly/daily data, minute data for selected electrical
    objects, and RMS waveforms plus action chains for important events. CSV and JSON exports carry units.
12. The player can edit retail offers and network fees for future contracts. Existing contracts keep
    their terms, and residents and firms select among eligible offers at renewal.
13. Acceptance combines physical reference checks, conservation, macro-scale comparison, declared
    assumptions and sensitivity tests. Missing empirical coefficients do not silently become facts.

The calendar begins on 1 January, Fantasy Era year 1. Years contain 365 days, local time is fixed at
UTC+1, and there is no daylight-saving transition.

## World and time

Gutnö is close to Gotland in area, latitude, population and economic scale without reproducing real
infrastructure. The coastline and 18 economic zones support towns, villages, farmland, forest,
limestone heath, wetlands, quarries, reserves and shore. Half-kilometre land parcels affect siting,
surface roughness and population display. Wind turbines cannot be placed in settlements, quarries,
reserves or on shore and must satisfy the residential setback.

Weather is continuous and deterministic for a seed. Monthly wind, temperature, humidity and solar
means come from the NASA POWER 2001–2025 climatology at 57.5° N, 18.5° E. Wind variability,
persistence and direction use summary statistics fitted to NASA POWER hourly data for 2020–2024.
Visby's monthly mean daily temperature range corrects the maritime grid cell's understated day/night
range. Solar position controls sunrise, sunset and the client palette; snow follows persistent cold.
The wind field combines the weather anomaly, Global Wind Atlas mean wind at 100 m, land-cover shear
and a smooth spatial/temporal perturbation. Jensen/Park wakes use root-sum-square superposition.

One authoritative `World` owns the event clock, random streams, ledger, projects and histories. Its
minute loop integrates the interval just completed, settles hour/day/month boundaries, accepts new
plans, dispatches, solves AC power flow and applies protection. Events within a minute run at their
own timestamps. Protection has priority over restoration, commissioning and economic activity at the
same time. Persistent event IDs and command receipts make retries idempotent.

The modules exchange versioned `ActivityPlan`, `DemandTrajectory`, `PhysicalResult` and
`EconomicSettlement` envelopes. They identify intent, forecast and actual intervals separately. A
saved contiguous settlement watermark prevents a repeated interval from billing or producing twice.

## Society, firms and material flows

Residents are represented by POP cohorts by zone and activity: industry, agriculture, hospitality,
services, public services, construction, retired and youth. Visitors, holiday-home users and seasonal
workers are also POPs. The initial scenario has about 55,300 residents and roughly 190 cohorts; cohort
splitting and ageing are supported up to the 10,000-object limit. People, employment and money move
together, and the monthly identity `end = start + births - deaths + immigration - emigration` is kept.

Daily behaviour includes wages and transfers, necessities, discretionary spending, shopping trips,
tourism arrivals and departures, and accommodation/ferry limits. Monthly behaviour includes ageing,
retirement, hiring, layoffs, retraining and logit migration. Job access, actual contract cost,
commuting, housing, amenity, outage history and water service enter the decision. POP preference,
elasticity and migration-inertia differences are deterministic for a seed.

Large industrial and public actors are individual firms: cement and quarrying, food processing,
brewery, ferry terminal, hospital, construction and waterworks. Services, hospitality, public services
and agriculture are aggregated by zone. Every industrial recipe is bounded by equipment capacity,
staff, input stock and output space. Output follows actual equipment service; trips and an eight-hour
cement-kiln warm-up therefore affect production. Per-good accounts record opening stock, production,
recipe use, imports, household use, exports, liquidation and closing stock in the good's own unit.

Island goods markets clear between mainland import/export parity within transport capacity. Firms
make bounded decisions about production, employment and expansion. Private credit is limited to two
months of payroll plus 25% inventory collateral, with a 0.25 MSEK minimum facility. The assumed APR is
8%. Surplus cash repays debt; persistent distress can shrink employment and after 30 days cause exit.
Liquidation records stock sales, bank recovery/loss, equity and job losses. These credit rules are
game-design assumptions, not a calibrated Swedish credit model.

Public waterworks use electrical pumps and finite tanks. The assumed use is 0.12 m³ per resident-day
and 0.22 m³ per visitor-day, with 0.65 kWh/m³ pumping energy and two design-days of storage. An outage
first drains the tank; a shortage affects later tourism and residential attractiveness. Groundwater
availability is capped at pump rating; drought hydrology is outside this release.

## Contracts, prices and accounting

Signed contracts contain their price rule, markup, network fee and expiry. Fixed contracts preserve
their signed price. Indexed contracts use the signed hourly or previous-calendar-month reference.
Customers compare expected cost plus a small risk premium when a contract expires. The player edits
offers for new contracts, not contracts already in force.

Equipment plans use the same marginal contract price later used for the delivered-energy bill. The
hourly settlement bills integrated service and never a forecast. Mainland energy is bought or sold at
the external reference price with declared fees.

All cash moves through a double-entry ledger, including trade, wages, bills, tax/benefit transfers,
credit, construction, visitors and migration. `external`, `bank` and financing accounts make the
boundary explicit. Daily conservation reports cover money, every material and the public-water stock.
Powerbolaget projects remain free investments with visible cash and financing rather than using the
private-firm credit model.

## Load model

Households, services, public buildings, lodging and farms use smooth activity profiles. A new hourly
plan anchors at current demand and ramps toward the target, so the hour boundary does not create a
step. Household heating uses a zone thermal state, outdoor temperature, thermostat schedule and
temperature-dependent heat-pump COP. Outages cool buildings and restoration produces cold-load pickup.

Industrial devices use off, starting, running, stopping, warm-up and tripped states. Commands are
timestamped events. Each device maps to an electrical bus and to the party billed for delivered energy.
The initial non-industrial load shapes carry the declared `DEMAND_SCALE` calibration factor; the
sensitivity record varies it rather than treating it as measured truth.

## Steady electrical network

The opening grid contains a synthetic 110 kV ring, 110/20 kV zone supply, 33 kV wind collectors,
individual 0.69 kV turbine buses and unit transformers, the cement supply and two 130 MW HVDC poles.
It has six wind farms, 54 turbines and 158 MW nameplate. OpenDSS through OpenDSSDirect.py solves the
positive-sequence constant-PQ AC network every simulated minute. Every solution must pass finite-value,
loss and source plausibility checks; a failed retry increments `numerical_failures` and retains the last
valid state. A solver failure is never reported as a physical blackout.

Automatic dispatch respects link margin, source P/Q/current capability, storage SOC/reserve and oil
unit limits. Storage can shave import, absorb surplus wind or form an island. Wind curtails
proportionally when necessary. Remaining deficit sheds flexible, commercial, residential, industrial
and critical load by priority. Stable islands restore shed load in stages as reserve permits.

Wind and storage converters support fixed-Q or voltage-droop operation inside an assumed 1.1 pu
apparent-power circle and voltage-dependent current limit. Storage loses 1.5% capacity per calendar
year plus 20% per 6,000 equivalent cycles and retires at 80% state of health. Replacement restores
condition while preserving stored energy up to the new limit.

Fuel-oil engines take ten minutes to start, have 30/15-minute minimum up/down times, 20% minimum output
and a 20%-of-rating/minute ramp. Fuel, electricity and rejected heat are separate at an assumed 38%
efficiency. Delivered fuel costs 950 SEK/thermal MWh and start cost is 8,000 SEK/MW. Low stock triggers
a visible reorder. A running black-start unit may form an island.

Player link projects accept HVDC or HVAC technology, capacity, landing station and route. The assumed
contracted envelopes are 640 MW total HVDC and 440 MW HVAC, with three/four-year lead times and explicit
costs. Historical dates in scenario metadata do not commission anything. When HVAC exists and is
healthy, the mainland AC source is the 50 Hz reference and HVDC carries scheduled power. Otherwise a
healthy forming HVDC can resume the reference role.

## Faults, protection and event dynamics

Weather, age and maintenance modify hourly fault sampling. Transient overhead faults may auto-reclose;
permanent faults remain isolated until repair. Physical normally-open 20 kV ties replace statistical
served fractions: after 45 minutes, a separate AC study accepts a transfer only when voltage stays at
least 0.90 pu and current stays within the tie rating. The islet sea cable has no alternate feed.

Short-circuit studies run on the actual switched network and enabled forming sources in a separate
solver context. IEC 60255 standard-inverse overcurrent relays use measured current, 1.25 times continuous
rating pickup, TMS 0.08, 60 ms breaker delay and 300 ms upstream grading per zone. Relay-disabled and
below-pickup cases stay explicit. Thermal overload protection and repair/reclose logic operate on their
own time scales.

An important fault or source transition opens a ten-second, 20 ms positive-sequence RMS window.
Classical/virtual swing equations, first-order droop and voltage regulators advance with RK4; native AC
algebraic solves return P, Q and V for the next differential step. Farms aggregate frequency response
while their individual steady-state branches and turbine statuses remain in the main network. The
mainland AC grid is an infinite 50 Hz reference. Synthetic VSC-HVDC and batteries use H=1.5 s, 5% droop
and a 50 ms governor; oil engines use H=3 s and a 500 ms governor. Converter virtual impedance limits
current. These values are declared teaching assumptions.

Underfrequency stages shed 10%, 25% and 45% at 48.8, 48.2 and 47.5 Hz. Voltage ride-through delays are
150 ms below 0.2 pu, 2 s below 0.85 pu and 200 ms above 1.12 pu. Actual voltage-dependent service,
generator output and three-phase fault-resistor heat are integrated. Event waveforms, source state,
relay progress and the action chain are saved and exportable.

This event model is an averaged balanced RMS teaching model. It does not simulate EMT switching,
harmonics, phase imbalance, detailed manufacturer controls or actual Gotland converter behaviour.

## Engineering and asset life

The construction catalogue includes PB-2.3/PB-3.6/PB-5.6 wind turbines, grid-following or grid-forming
storage, backup oil generation, 20/33/110 kV lines and collectors, 110/20 or 110/33 kV stations and
transformers, and mainland interconnectors. The server previews siting, voltage compatibility, route
length, impedance, cost, duration, connection and operational lockout. A read-only impact study clones
the current state and compares convergence, served demand, losses, minimum voltage and overloads before
and after commissioning. The player can then edit or commit the project.

Construction pays by progress and records material use. Winter affects duration. Asset work locks the
equipment out; cancellation retains sunk cost. Refurbishment restores condition, battery replacement
restores cells, and conductor upgrades add 10% rating. Retired turbines stop operating costs, wake
effects and spacing exclusions.

All engineering prices, work durations, mainland envelopes and most failure/repair coefficients are
assumptions collected in `app/params.py` or beside the model that uses them. `results/acceptance-sensitivity.json`
records selected ±20% and ±10% variations.

## History, saves and interfaces

The archive retains 168 hourly and 30 daily rows per object, 1,440 minute samples for each of up to
eight selected electrical objects, and eight RMS event windows. Device and turbine energy fields are
integrals; state fields are labelled snapshots or means. CSV headers contain units; JSON includes
schema, interval, units, data-quality and retention metadata. Held values are explicitly marked.

The archive is canonical JSON compressed with zlib, base64 encoded and protected by SHA-256 in saves.
Loading caps decompressed history at 64 MB, checks the digest and validates object references and
numeric solver state. The whole POST body is capped at 12 MB. Older uncompressed archives remain
readable. Browser autosaves contain complete world, event, random, partial-period and history state.

The API boundary in `app/main.py` provides session creation/load, ticks, commands, build preview,
work preview, save, entity/parcel details, paged tables, layered history, module exchanges and land
data. Mutating POSTs require the game header and a same-origin request. Simulation workers own their
OpenDSS contexts and sessions; the client never mutates authoritative state directly.

The web client provides island, electrical and economy views, map layers, routed line selection,
flow/loss/reactive-power displays, inspectors, construction and work dialogs, tariff controls, pinned
objects, projects, conservation results and CSV/JSON exports. The economy POP table is filtered,
sorted and paged on the server in blocks of 100 so the 10,000-object case does not enter the DOM at once.

## Evidence and limits

`docs/VALIDATION.md` records analytic references, automated tests, annual no-player behaviour, scale,
browser performance and sensitivity. The source inputs stored with the model are:

- `app/island-climatology.json`: NASA POWER climatology, including query URL and period;
- `app/island-wind.json`: Global Wind Atlas v4 mean wind at 100 m, CC BY 4.0, including source URL and
  the transformation into game cells;
- `app/weather.py`: the Visby station daily-range source and the documented hourly-fit summaries.

Published Gotland electricity, population and industry totals are macro comparison points. They do not
validate individual fictional zones or firms. Model coefficients without a cited input are assumptions.
The first release also defers offshore wind, solar and gas construction, a nodal electricity market,
detailed road/ferry traffic, drought hydrology, unbalanced/EMT studies and manufacturer-specific controls.
