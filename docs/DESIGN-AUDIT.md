# Initial design audit

This audit compares the implemented first release with
`Powerbolaget_游戏设计与仿真技术规格书_v0.2.md` and the thirteen owner decisions recorded in
`MODEL.md`. It distinguishes implemented behaviour from validation evidence. A feature is not marked
complete merely because a UI control or data field exists.

Status date: 5 November 2026. Core source under review: `ef3afcb`; `a02bc72` refreshes only acceptance
evidence. The corrected autonomous-year run is still in progress, so this is an implementation audit,
not final release acceptance.

## Overall finding

The repository is a functional engineering alpha with a coherent vertical path from autonomous people
and firms through device demand, AC power flow, protection, settlement, history and the web client. M0
is complete. Most of M2 is implemented. M1 and M3 remain partial because wind-farm event dynamics,
annual calibration, per-value provenance/explanation and classroom usability have not met the original
acceptance conditions.

The current evidence is substantial: 69 Python checks and five Chromium workflows pass; steady-state,
protection and source-control equations have independent references; the 10,000-POP/600-turbine scale
fixture completes without solver failures; and bounded history, saves and browser rendering have been
measured. Those checks establish the properties stated by their fixtures. They do not validate the
fictional economy or turn assumed parameters into Gotland measurements.

## Confirmed product decisions

| Initial decision | Status | Current evidence and remaining issue |
|---|---|---|
| Open-ended regional energy/economy simulation | Complete | There is no score, victory condition or forced transition path. Weather, firms, people, tourism and faults evolve without player input. |
| Player controls Powerbolaget; firms and residents remain autonomous | Complete | Energy construction and policy are player commands. Firm production, hiring, investment, credit/exit and POP migration are model decisions. |
| Gotland-scale fictional island, not a digital twin | Mostly complete | The world is explicitly fictional. NASA POWER and Global Wind Atlas data carry source and licence metadata; zones, firms, wiring and controls are synthetic. Many individual assumed coefficients are identified only by the module-level statement in `params.py`, rather than carrying a machine-readable source record of their own. |
| Energy, economy, society and load models share one world core | Complete | One authoritative `World` owns time, random streams, events, ledgers and module state. Solver access is isolated behind one adapter contract. |
| Layered events, POP state/probability and bounded-rational firms | Complete at model level | Minute, hour, day and month boundaries coexist with timestamped protection/RMS events. POP and firm mechanisms are implemented. Their real-world coefficients still need calibration. |
| About 20 regions and a 10,000-POP-object cap | Complete | The opening world has 18 economic zones and about 190 POP objects. The hard cap is 10,000; the synthetic full-limit fixture has been measured. |
| Multi-rate time model | Complete | Grid operation is sampled each minute, important electrical events use 20 ms steps, and social/economic processes use hourly/daily/monthly boundaries. |
| Individually connected and inspectable wind turbines | Partial | All 54 opening turbines have individual buses, transformers/collectors, weather, P/Q, fault and maintenance state. During a 20 ms event, however, wind remains a static network injection. There is no wind-farm dynamic state or single-turbine-versus-aggregate dynamic benchmark. |
| Continuous minute demand with real discrete events | Complete for the implemented load types | Hourly targets ramp continuously; motors, trips and protection retain discrete timing. Requested and served energy are integrated separately. |
| Measure performance before setting a speed target | Partial evidence | CPU, solve latency, memory, save size and browser FPS are measured at four scales. The corrected 365-day run is not yet complete. A full-limit fixture costs 2.39 CPU seconds per simulated hour, so high game speeds at that synthetic maximum remain limited on one core. |
| Three views with layers, inspector and pinned objects | Functionally complete; UX validation open | Island, grid and socioeconomic views, shared selection, map layers, inspection, pins and exports work in Chromium. Metric-level formula/source drill-down and classroom usability testing are missing. |
| Free PB investment, explicit finance, simple contracts/tariffs and automatic operation | Complete at first-release depth | PB shortfalls are explicit external financing; private firms use finite credit and may exit. Signed contracts, retail policy, mainland settlement and automatic dispatch exist. This is intentionally not a nodal market. |

## Thirteen later first-release decisions

Decisions 2-12 are represented by executable behaviour and tests: grid-forming VSC-HVDC and HVAC
handover, automatic islanding attempts, editable suggested engineering, player-led interconnectors,
wind/oil construction, contract-price response, finite private credit and exit, activity/device demand,
the web client, layered history/export and editable new retail contracts.

Decision 1 is only half complete. Individual steady-state turbine connections are implemented, while
station/farm aggregated event dynamics are not. Decision 13 is also partial: physical references,
conservation, declared assumptions, scale and local sensitivity exist, but the corrected autonomous
year, annual macro calibration, parameter interactions and student usability evidence do not.

## Milestone assessment

### M0 — unified data and interfaces: pass

- Hour boundaries do not create artificial aggregate P/Q steps.
- Minute energy, requested/served demand, ledger money, goods, water and population identities have
  direct regression checks.
- Event and command IDs prevent repeated actions and repeated settlement across save/load.
- Physical trips interrupt equipment immediately and restart timing is preserved.
- Four named exchange envelopes exist and distinguish intent, forecast and actual data. Their current
  payloads are mainly world-level summaries; they are not yet the full per-owner/site protocol sketched
  in section 7 of the specification.

### M1 — physical network and per-turbine wind: partial

Completed:

- OpenDSS positive-sequence steady-state network with individual turbines and collector branches.
- P/Q capability, voltage, loading, losses, storage/oil constraints, faults, graded protection,
  reclosing, physical feeder transfer and restoration.
- Aggregated positive-sequence source dynamics for HVDC, forming batteries and oil generation, coupled
  to the AC network every 20 ms.
- Independent checks for a two-bus AC solution, RK4 source dynamics and IEC inverse timing. Numerical
  failures are distinct from physical blackouts.

Open:

- Wind-farm converter/aerodynamic frequency and voltage response during the event window.
- A benchmark comparing a single-turbine model with the chosen farm aggregation and checking post-fault
  turbine states, power, voltage and frequency.
- External dynamic-tool or published standard-case comparison. Current dynamic evidence is analytic
  and native-network reference testing only.
- EMT, harmonics, phase imbalance and manufacturer controls are explicitly outside first-release scope.

### M2 — autonomous economy and spatial POP loop: implemented, not calibrated

The model has 12 goods, 69 opening firms, labour/capacity/input-constrained production, inventory and
trade, contracts, credit/exit, tourism, births/deaths/migration, construction demand, water and thermal
loads. Outages trip equipment and affect production; contracts affect scheduling; firms can shrink,
expand or exit; population and employment feed future demand.

The opening economy has not yet passed an annual calibration target. In the corrected no-player run,
several regional service firms are accumulating debt and one firm has exited by mid-year. This may be
a valid scenario outcome or a coefficient imbalance; only the completed year and comparison against
declared ranges can decide. Existing sensitivity covers three winter days one factor at a time, so it
does not establish annual macroeconomic stability or causal response across multiple seeds.

### M3 — full opening world and three views: partial acceptance

The 18-zone opening world, three web views, turbine/line/substation/storage/oil/interconnector tools,
impact preview, history, saves and CSV/JSON export are functional. Browser tests verify the primary
paths and full-scale rendering.

The original acceptance still lacks:

- a completed corrected 365-day run with annual energy, population, firm, debt, outage and numerical
  drift review;
- direct user testing with KTH students or engineers;
- third-level explanation for important metrics: composition, formula, source/assumption and linked
  objects are not consistently available from the metric itself;
- broader scenario campaigns for prolonged islanding, player-built networks, extreme weather and
  fault-rate claims.

## Priority before calling the first release complete

1. Implement real farm-level RMS states and response, then add the single/aggregate wind dynamic
   comparison required by M1. Correct the documentation so it does not call static wind injection a
   completed farm dynamic model.
2. Finish and inspect the corrected autonomous year. Set explicit acceptable ranges for annual energy,
   peak/seasonality, population, employment, firm exits/debt and conservation residuals; tune only with
   declared assumptions and rerun the affected sensitivities.
3. Give each observed, assumed and fictional parameter a structured provenance record and expose the
   source/formula/decomposition from the relevant UI metric.
4. Add end-to-end scenario evidence that contract price and outage history change firm decisions and
   future demand, then run multiple seeds for any probabilistic claim.
5. Run a small classroom usability study focused on causal understanding, engineering feedback and
   navigation depth.

Until items 1-3 are closed, the honest release description is “feature-complete engineering alpha for
review,” rather than a validated teaching release.
