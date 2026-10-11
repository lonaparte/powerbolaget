# Powerbolaget model documentation

Version: 0.0.1. The game demonstrates constraints between wind farms, batteries, collectors and protection while supplying an unnamed Baltic coastal city with external-grid backup. Costs, schedules, weather synthesis and relay settings are scenario assumptions rather than field engineering data or recommended settings.

## Electrical structure

```text
External grid: 110 kV / 1000 MVA short-circuit capacity
       ↕ 31.5 MVA, 110/35 kV transformer, X = 10%
35 kV bus ← two radial collectors ← 0.69/35 kV unit transformers ← turbines
       ↕ PCS + battery storage
       ↓ 20 MVA, 35/10 kV city transformer, X = 8%
10 kV feeders → harbor / center / homes / water and hospital
```

OpenDSS solves the balanced three-phase AC network in snapshot mode every 15 minutes. Wind and storage use controlled P/Q equivalents; districts use aggregated constant-power loads with fixed power factors. Lines have positive- and zero-sequence R/X/C parameters. Transformers include copper and no-load losses. Each original turbine has a 5.5 MVA transformer. Station auxiliaries consume 50 kW.

| Item | Initial/default value | Expansion/behavior |
|---|---|---|
| Wind | 4 × 5 MW | 8 × 5 MW; calculated schedule |
| Collectors | Two strings, up to four turbines each, 300 A | Upgrade to 500 A; calculated schedule |
| Storage | 6 MW / 24 MWh | 12 MW / 48 MWh; calculated schedule |
| Import/export limits | 12 / 5 MW | Adjustable from 0 to 20 MW |
| Aggregated load ratings | Harbor 3.2, center 3.5, homes 4.2, water/hospital 1.8 MW | Seasonal and diurnal factors |
| Critical load fractions | 55%, 30%, 20%, 85% | Noncritical load is shed first, proportionally |
| Voltage target | 0.94–1.06 pu | Curtail or shed after reactive control |

The first collector section is 2.5 km and subsequent sections are 0.882 km, with R1 = 0.12 Ω/km and X1 = 0.10 Ω/km. City feeders are 1.8–4.1 km with R1 = 0.12 Ω/km and X1 = 0.09 Ω/km. Collector upgrades change ampacity only, representing additional capacity without detailed construction or cable thermal modeling. The city is a moderate-size demonstration district. The map is schematic; impedances use explicit parameters rather than screen distances.

## Turbines and wakes

The 5 MW rating, 126 m rotor, 90 m hub, 3 m/s cut-in, 11.4 m/s rated speed and 25 m/s cut-out follow the [NREL reference turbine report](https://www.nrel.gov/docs/fy09osti/38060.pdf) and its [PNNL listing](https://tethys.pnnl.gov/publications/definition-5-mw-reference-wind-turbine-offshore-system-development).

Power uses cubic interpolation between cut-in and rated points, then clips at rated power. Ideal-gas density corrects equivalent wind speed. This is not an OpenFAST aeroelastic simulation. After storm shutdown, wind must remain below 20 m/s for two intervals before restart; this rule is a scenario assumption.

Directional Jensen-type wakes use expansion coefficient 0.05 and thrust coefficient 0.8. Multiple deficits combine by root-sum-square. Rotor overlap uses a smooth local approximation rather than exact area integration. Original spacing is 7D / 5D. Stopped turbines produce no operating wakes. Site roughness, terrain, turbulence intensity, thrust curves, yaw control, wave loads and cable installation dynamics are omitted; results do not establish energy guarantees or structural loads.

## Storage and dispatch

Physical SOC limits are 15%–90%; initial SOC is 60%. Charge and discharge efficiencies are each 96%, giving 92.16% AC round-trip efficiency. Each interval is 0.25 h; positive P means discharge:

- Discharge: `E_new = E_old − P × dt / 0.96`.
- Charge: `E_new = E_old − P × dt × 0.96`.
- PCS active power is limited by MW rating, reactive power by the apparent-power capability circle; storage S = 1.1 × rated P.

Wind serves the city and auxiliaries first, then charges batteries, exports within the limit and finally curtails. Self-use discharges to a normal reserve SOC of 30%; insufficient backup permits further discharge to 15%. The reserve strategy supplies only deficits beyond the import limit. Noncritical loads are shed before critical loads. If imports are disabled and available energy cannot cover auxiliaries and no-load losses, the station stops and is reevaluated next interval.

Dispatch iterates with actual AC losses and limits currents, city-transformer loading and voltage. Reactive control is a finite-gain Volt-var approximation; original turbines operate within a 5.5 MVA capability circle. Battery temperature, degradation, cell imbalance, electrochemical resistance and DC-bus dynamics are omitted. SOC represents aggregated stored energy.

Expansion batteries commission at minimum SOC. Adding 24 MWh adds 3.6 MWh stored energy, requiring 3.75 MWh purchased precharge; 0.15 MWh is conversion loss. This is commissioning energy settlement rather than an instantaneous PCS simulation. Initial and commissioning energy are excluded from wind generation. Direct wind share is `min(wind power, city power served) / city power served`, excluding battery discharge.

The energy ledger checks: wind + imports = served load + exports + network losses + auxiliaries + storage energy change + battery conversion losses, allowing solver residuals. Dispatch reference: [NREL SAM](https://samrepo.nlr.gov/help/battery_dispatch_fom.html).

## Faults and protection

Fault controls include collector A/B three-phase short circuits, a harbor-feeder short circuit, a city-transformer internal fault, grid outage and a BMS fault. Separate OpenDSS studies use a 0.01 Ω three-phase fault with generators and loads disabled, reporting external-grid contribution on the commissioned topology. Converter current limiting, negative-sequence control, PLL behavior and dynamic fault ride-through are omitted. References: [EPRI fault studies](https://opendss.epri.com/FaultStudies.html) and [generator model](https://opendss.epri.com/Generator.html).

| Function | Implementation | Omitted behavior |
|---|---|---|
| 50 | Current ≥ 8 × pickup; 30 ms trip | Sampling/filtering and transient overreach |
| 51 | IEC standard inverse shape; default TMS 0.12 | Full-network coordination scan |
| 87T | Known internal zone; ideal 30 ms criterion | CT differential, restraint and inrush blocking |
| 50BF | 200 ms after local breaker failure, then 60 ms upstream opening | Redundant coils/circuits |
| 86 | Lockout until repair and manual reset | Physical latching relay |
| 27 / anti-islanding | Known grid outage; 200 ms trip plus 60 ms opening | Frequency/ROCOF detection |
| BMS / PCS | Known fault; storage isolation in 80 ms | Cell temperature/voltage and fire response |

The 51 curve is `t = 0.14 × TMS / ((I / I_pickup)^0.02 − 1)` and does not operate below pickup. Default pickup is 1.2 × circuit ampacity; upstream backup uses independent timing. Slow local settings can make upstream backup trip first and expand isolation. Breaker failure and upstream backup operate in arrival order. Reference: [SEL IEC standard inverse explanation](https://selinc.com/api/download/120078/id/128502/0/). Settings are experimental, not field recommendations.

Normal breaker opening takes 60 ms. Failure expands isolation to the farm export breaker or city transformer. The millisecond timeline is discrete event logic; energy is integrated over later 15-minute intervals. No transient voltage or rotor waveform is computed.

Single-phase earth faults, zero-sequence/directional protection, arcs, CT saturation, distance protection, communications differential, reclosing coordination, low-voltage ride-through, frequency stability and relay hardware validation are omitted. Grid-following turbines and batteries trip after loss of the grid. Island supply would require grid-forming PCS, switching controls, voltage/frequency dynamics and black-start validation.

## Economics and validation

Initial funds are CNY 220 million. Standard expansions cost CNY 140 million for wind, 32 million for storage and 16 million for collectors. Sale/import/export rates are CNY 0.62/0.65/0.28 per kWh; variable wind cost is 0.07, unserved-energy penalty is 8, and fixed O&M is CNY 3,000/day. These gameplay assumptions exclude finance, tax, decommissioning, insurance and market quotations.

Tests cover curves, density, wakes, storm restart, SOC/energy conservation, low-wind supply, outages without imports, six faults, breaker failure, repair, commissioning, saves, conflicts and input rejection. `tests/endurance.py` checks every interval of one year. Passing it does not establish grid-code compliance or engineering acceptance.

## Custom planning and electrical topology

Each farm has exactly one substation, up to 24 turbines, 41 nodes, 80 cables and 120 MW. Up to four farms can be approved per scenario. IDs are strictly validated against OpenDSS command injection. Disconnected drafts can be saved, but approval requires every node to have a closed path to the substation. Normally open ties, parallel branches and closed rings are supported; rings warn that directional protection needs separate design.

Every cable creates an actual OpenDSS Line using entered length, R1/X1/C1 and ampacity. Each turbine creates a Generator and individual Transformer. Transformer capacity, reactance and 35/66 kV voltage enter power flow. Farm output connects to the common onshore 35 kV bus through a site-transformer equivalent. Separate long export cables and offshore 220 kV platforms are omitted. New storage aggregates at the common bus. Cable and transformer limits curtail the affected farm.

Rated power and cut-in/rated/cut-out speeds define turbine curves. Hub height uses a 0.11 power-law shear correction; rotor diameter and coordinates enter within-farm directional wakes. Cross-farm wakes are omitted. The 5 MW template uses NREL anchors; 8/12 MW templates are assumed rather than vendor-certified.

Approval freezes parameters and schedule. Commissioning inserts equipment at an interval boundary and settles minimum-SOC precharge. Validation previews current weather and approved farms rather than all lifetime conditions. Existing protection targets the original collectors, harbor, city transformer, grid and BESS; custom cable selectivity, directional coordination and N-1 design are not implemented.

## Continuous Baltic coastal climate

The setting is an unnamed Baltic coastal city. NASA POWER 2001–2020 monthly WS10M, T2M and ALLSKY_SFC_SW_DWN data calibrate coefficients; historical days are not replayed. Raw grid coordinates remain calibration metadata, not a named game location. Data and source metadata are in `app/baltic-coastal-climatology.json`.

With t measured in continuous days from 2030-01-01, seasonal baselines use three Fourier harmonics:

```text
F(t) = a0 + Σ[k=1..3] { ak cos(2πkt/365) + bk sin(2πkt/365) }
```

Wind and temperature fit monthly means; irradiance fits logarithms and exponentiates to remain positive. A fixed seed determines random knots. Sixteen lagged white-noise terms weighted by `0.72^k` create persistent weather. Quintic interpolation `w(u)=6u^5−15u^4+10u^3` matches first and second derivatives at knots. Refreshes, repeated operations and midnight do not resample weather.

10 m wind combines seasonal functions, smooth lognormal perturbations, a diurnal term and two-hour gusts. 90 m wind is `wind10 × 9^0.11`. Temperature combines seasonal, weather and cloud-modulated diurnal terms. Direction has an eight-day cycle and shared disturbances; continuity uses circular differences. Clouds vary at daily and four-hour scales. Wave height is the proxy `max(0.25, 0.35+0.025*v10²+0.15*smooth_noise)`, not a measured spectrum or hydrodynamic model.

Solar elevation uses latitude, continuous declination, hour angle and equation of time. Surface irradiance combines positive elevation, seasonal irradiation and smooth cloud perturbations, limited to 0–1100 W/m². It is zero at night and continuous at sunrise/sunset. Fixed CET/UTC+1 avoids daylight-saving jumps. Daily irradiation integrates 96 samples and is not used to reconstruct instantaneous radiation. Daylight means astronomical day length rather than measured sunshine.

Climate is continuous across days, months and years; random processes do not reset annually. Explicit calm/storm/gust modes are operator stress tests and do not alter natural construction weather. Temperature affects heating demand. No solar generators are installed, so irradiance is environmental information only.

Data service: https://power.larc.nasa.gov/docs/services/api/temporal/climatology/

Calibration request: `https://power.larc.nasa.gov/api/temporal/climatology/point?parameters=T2M,WS10M,ALLSKY_SFC_SW_DWN&community=RE&longitude=12.5683&latitude=55.6761&format=JSON&start=2001&end=2020`.

The baseline is gridded data, not offshore mast measurements. Random intensity, correlation time, shear and wave relationships are not site-calibrated; annual results do not establish P50/P90 guarantees.

## Quantities, resources and critical path

The original scheduler approximates work quantities, dedicated resources, dependencies and hourly weather windows. It does not import ORBIT. Productivity is an explicit scenario assumption. Method reference: https://nlrwindsystems.github.io/ORBIT/tutorials/project_manager.html.

- Survey/design: `80 + 8×turbines + 2×cable_km + 2×water_depth_m` hours. Onshore teams work 8 h/day, rounded to full days.
- Manufacture/delivery: maximum of turbine, transformer, battery and cable lead times. Turbines use `45 + 6×largest_unit_MW + 2×turbines/supply_lines` days, rounded up.
- Foundation work per unit: `20×(unit_MW/5)^0.65×(1+depth/80) + round-trip transit` hours; fixed foundations cover 5–60 m depth.
- Lift work per unit: `12 + hub_m/8 + rotor_m/12 + 3×unit_MW + transit` hours.
- Cable work: `8 + length_km/0.25 + transit` hours. Transit assumes 10 knots and the configured port distance.
- Foundation weather: 10 m wind ≤14 m/s and waves ≤2.2 m; lifting ≤12 m/s and ≤1.8 m; cabling ≤15 m/s and ≤2.0 m. The same climate function checks hourly work blocks up to 6 h; vessels wait if limits are exceeded.
- Lifting and cabling can overlap after foundations; onshore electrical work can overlap after delivery. Commissioning waits for all prerequisites. The longest dependency chain is the critical path.
- Resources are dedicated to each farm rather than shared. Vessel costs include occupied phase days and weather delay: CNY 180,000/day for foundations, 240,000 for installation and 130,000 for cabling.

The commissioning date freezes at approval. The seed defines the full weather sequence, which the scheduler uses in advance; actual forecast uncertainty is omitted. Permits, seabed surveys, supply disruption, shared-vessel queues, accidents, tides and wave-period constraints are omitted.

Base cost is `rated_MW×7,000,000 + cable_km×900,000 + transformer_MVA×180,000 + storage_MW×800,000 + storage_MWh×1,100,000 + 2,000,000`, plus vessel cost. Standard expansions retain their original cost assumptions and use the same scheduler. CNY is a gameplay accounting currency rather than a local project quotation.
