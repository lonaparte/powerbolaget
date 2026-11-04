# Powerbolaget 0.1.0 — validation record

Everything below was run on 4 November 2026 on the release commit's code. The machine was one core of a 2.1 GHz Intel Xeon server, Linux, with Python 3.12. The pinned dependencies came from `requirements.lock`, with OpenDSSDirect.py 0.9.4 and DSS-Python 0.15.7.

## Automated tests

`python -m pytest -q -p no:cacheprovider`: **25 passed** in about 11 s.

| Area | Test | What it checks |
|---|---|---|
| Core | `test_fantasy_era_calendar_starts_on_year_one` | Minute 0 is FE 1 · 01 Jan · 00:00, a Monday. Years roll over after 365 days, and sub-minute timestamps format correctly. |
| | `test_streams_are_independent_and_resume_exactly` | Named random streams do not disturb each other and resume bit for bit after saving. |
| | `test_events_run_in_time_then_priority_order_and_survive_saving` | Events at sub-minute timestamps run in time order, then by priority group. Ids never repeat after reload. |
| | `test_ledger_never_creates_money` | Every transfer has a payer and a payee, so all accounts sum to zero. |
| | `test_weather_follows_the_island_climate` | Over a simulated year: wind variability and calms within the observed range, south-west the most common direction and every direction occurring, a July daily temperature swing near Visby's, an 18-hour midsummer day and a 6.5-hour midwinter day, and light June nights. |
| World | `test_money_people_and_jobs_balance_after_a_day` | After a full day: money sums to zero, employed people equal filled jobs per POP and per firm, the POP cap holds, no numerical failures. |
| | `test_monthly_population_account_is_exact` | `end = start + births - deaths + immigration - emigration`. |
| | `test_hourly_plans_do_not_step_the_load` | Over three hours, no aggregated load changes across an hour boundary by more than four times its median minute-to-minute change. |
| | `test_every_minute_balances_power` | At the end of a day: mainland exchange + wind + storage = served load + losses, within 0.05 MW. |
| | `test_energy_bookkeeping_matches_the_minutes` | Hourly energy equals the integral of the minutes; served ≤ requested; wind ≤ available. |
| | `test_outage_trips_equipment_at_once_and_restart_waits` | Opening the cement works' feeder trips the kiln at once. After reclosing, the kiln is still in warm-up while homes are already served again. |
| | `test_fault_protection_and_repair_restore_supply` | A fault on the 20 kV feeder to Sudret trips it and de-energises the zone. Supply returns after auto-reclose or repair. |
| | `test_a_feeder_fault_is_sectionalised_before_the_repair` | A cable fault on a single-circuit feeder trips it. Within 150 minutes, switching re-feeds the zone except the 15–35 % on the faulted section, who are served again after the repair. A fault on the islet's sea cable leaves the islet dark until repair. |
| | `test_grid_forming_battery_carries_the_island_when_the_link_is_lost` | With both HVDC links lost, a 60 MW grid-forming battery becomes the voltage source, discharges and keeps most load served. |
| | `test_link_loss_without_grid_forming_is_a_blackout` | Without one, every load goes unserved, and this is not counted as a numerical failure. |
| | `test_hvac_link_takes_over_the_voltage_reference_and_fails_over_to_hvdc` | When the 220 kV link is commissioned, the mainland AC grid becomes the reference, the power balance holds and voltages stay below 1.06 pu. When the only AC cable in service is lost, the HVDC forms the island again and energised loads stay fully served. |
| | `test_same_seed_same_world` | Two runs with the same seed give identical SHA-256 digests of the full state after 4 hours. |
| | `test_save_and_load_continue_within_tolerance` | A world saved, serialised to JSON, validated and reloaded continues in step with the original: the same minute, event queue and population, and money within 1e-6 relative. Measured gap: about 2.5e-7. |
| | `test_building_a_turbine_commissions_it_into_the_power_flow` | Siting rules reject sea, town and quarry parcels. A turbine on farmland is built, paid for, commissioned and appears in the power flow. |
| | `test_saves_with_unsafe_ids_or_unknown_types_are_rejected` | Ids that could inject OpenDSS commands, and unknown catalogue types, are rejected before a world is rebuilt. |
| API | `test_a_new_game_runs_and_takes_commands` | Session, tick, command, preview, entity, parcel, table and save through HTTP. |
| | `test_requests_are_guarded` | Missing header, foreign origin and oversized bodies are refused. |
| Solvers | `test_calculation_libraries_are_imported_only_in_app_solvers` | Electrical libraries are imported only in `app/solvers/`. |
| | `test_backend_honours_the_solver_contract[opendss]` | The backend returns voltages, flows, losses and source power for a test feeder. |
| | `test_opening_a_branch_leaves_a_sane_solution[opendss]` | Regression test, see below. |

Browser tests (`node --test tests/browser_game.cjs`, Playwright with Chromium): **4 passed**.
- The game runs on its own after the page opens and every view renders. It opens in the day theme; night and the day/night cycle can be switched on, fade in rather than jump, and are remembered.
- A parcel shows its land, wind and turbine site, and a turbine can be built there.
- Reloading the page continues from the browser save.
- The layout fits a phone screen without horizontal scrolling.

`node --check` passes for every file in `web/js/`.

## An OpenDSS finding

Taking a branch out of service with `edit Line.x enabled=no` can leave buses with no admittance to ground. OpenDSS then reports a **converged** solution with meaningless values: in one case 553,791 MW of losses on a 60 MW island. That triggered overload trips across the network.

The fix:
- Switching opens the branch terminals (`open Line.x term=1` and `term=2`) instead of disabling the element.
- Every solution passes a plausibility check: finite voltages, losses and source power, and losses below a quarter of the total load and generation plus 5 MW. An implausible solution is retried once from a freshly built circuit; if that also fails, it counts as a numerical failure and the last valid state is kept.
- `test_opening_a_branch_leaves_a_sane_solution` keeps it fixed.

## Weather against the island's climate

The targets come from NASA POWER hourly data at the model's point, 57.5° N, 18.5° E (WS10M, WD10M and T2M, 2020–2024), and from Visby station averages for the daily temperature range. The model column is one simulated year (seed 1). Before 0.1.0's weather recalibration, wind was too steady (CV 0.34, 0.4 % calms, maximum 13 m/s), almost never blew from north-east to south-east, and had a 3 °C daily temperature swing all year.

| Measure | Observed | Model |
|---|---|---|
| Wind at 10 m, coefficient of variation | 0.45 | 0.43 |
| Hours below 2 m/s | 7.9 % | 6.3 % |
| Wind autocorrelation after 6 h / 24 h / 48 h | 0.73 / 0.36 / 0.22 | 0.74 / 0.31 / 0.18 |
| Wind from N, NE, E, SE, S, SW, W, NW (%) | 9, 8, 8, 9, 15, 25, 17, 10 | 8, 7, 6, 10, 17, 23, 20, 10 |
| Direction persistence after 24 h (mean resultant) | 0.47 | 0.56 |
| Daily temperature range, January / April / July | 3.9 / 8.6 / 8.2 °C (Visby) | 4.6 / 8.5 / 8.2 °C |
| Day length at midsummer / midwinter | 18.0 h / 6.6 h (astronomy at 57.5° N, with refraction) | 18.0 h / 6.6 h |

Snow lies on about 22–28 days a year, in five to eight cold spells (seeds 1–3).

## Another OpenDSS finding

OpenDSS `Circuit.TotalPower` adds up every voltage source. While a grid-forming battery carried the island, the mainland exchange therefore showed the battery's power. The backend now reads each voltage source's terminal power, so the mainland source and grid-forming batteries are reported separately. `test_grid_forming_battery_carries_the_island_when_the_link_is_lost` checks that the exchange is zero while islanded and that turbines plus battery balance load and losses.

## A year without the player

`tools/benchmark.py --days 365 --seed 1` runs the world from FE 1 · 01 Jan with no player input. The full record is in `results/benchmark-365d.json`.

| Measure | Result |
|---|---|
| Computation | 1,196 s for 365 days: 134.6 ms per simulated hour on average, 154 ms at the 95th percentile. |
| Power flow | 1.24 ms median and 1.89 ms at the 95th percentile per solve. No numerical failures. |
| Memory and saves | Peak 136 MB; a save is 1.5 MB. |
| Money | All accounts sum to 0.000 at the end of every day. |
| Energy | Load 635.5 GWh; wind 131.2 GWh (20.7 %); import 519.1 GWh; export 0.5 GWh. Peak 126.8 MW on 6 Jan; the lowest daily peak was 62.6 MW. |
| Supply | 46.8 MWh unserved (0.007 % of load). The largest event was a 20 kV cable fault on the old town's feeder on 25 Feb: switching re-fed the zone within the hour, and about 5 % of it waited 84 hours for the repair. |
| Population | 55,300 → 54,945: 509 births, 629 deaths, 1,428 immigrants and 1,663 emigrants. Region Gotland's forecast for 2025–2035, scaled to the same population, has about 2,300 people moving in and 2,180 moving out each year, so the model's gross flows are about two-thirds of that. |
| Visitors | Up to 16,600 at once. Lodging was full for 58 days in high summer. |
| Labour | 1,579 unemployed at the start (5.1 %), 3,632 in May, 417 in late September and 2,204 at the end of the year (7.2 %). |
| Firms | On 1 Sep an investor decided to build an 8 MW data centre, with a grid connection; firms went from 69 to 70. |
| Powerbolaget | Cash went from 400 to 546 MSEK. |

The first year run found two faults in the model, both now fixed:
- **Out-migration was missing.** In that run 1,325 people moved to the island but only 71 left, so unemployment drifted upward. Retirees were also counted as unemployed in the migration step. Off-island moves now have a base rate for life reasons, 40 % of school leavers leave to study or work, and immigration falls faster when unemployment is above 5 %.
- **Feeder faults lasted until repair.** In that run a cable fault left all 4,200 residents of the old town without power for 84 hours, which made up most of the 379 MWh unserved that year. Faulted 20 kV land feeders are now re-fed by switching (see `docs/MODEL.md`, section 6).

## Not validated

- No comparison against measured Gotland load, wind output or economic statistics. Every coefficient outside the NASA POWER climatology is an assumption.
- No dynamic (RMS or EMT) validation; the model has no dynamics.
- Unemployment is seasonal, but it peaks in May instead of in winter. The seasonal labour pattern is not calibrated.
- Browser tests run in Chromium only.
