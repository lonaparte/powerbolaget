# Powerbolaget 0.1.0 — validation record

This record separates reference checks, conservation, scenario behaviour and performance. A passing
test shows the stated property under its fixture; it does not turn assumed costs, controls or social
coefficients into measured facts.

## Provenance

The final regression run on 5 November 2026 used commit `416309b` plus documentation-only edits on
Linux 6.18, Python 3.12.14 and an AMD EPYC 9V74 host with a four-CPU cgroup quota. Dependencies are
pinned in `requirements.lock`, including OpenDSSDirect.py 0.9.4, DSS-Python 0.15.7 and NumPy 1.26.4.
The scale, sensitivity and browser artifacts identify their exact source commit (`d0ad057`); the next
commit changed documentation and stored those artifacts, not simulation or client behaviour.

Commands and results:

| Check | Result |
|---|---|
| `python -m pytest -q -p no:cacheprovider` | **69 passed** in 73.93 s |
| `node --test tests/browser_game.cjs` | **5 passed** in 14.49 s |
| JavaScript syntax checks | all files passed |
| `tools/deps.py check` | OpenDSS backend feeder check passed |

Pytest emitted one upstream deprecation warning: Starlette's test-client type alias references the old
AnyIO `BlockingPortal` alias. There were no test failures or application warnings.

## Numerical and physical references

These checks compare independent calculations or exact identities rather than echoing implementation
branches.

| Reference | Acceptance evidence |
|---|---|
| Balanced two-bus AC equation | OpenDSS receiving voltage agrees with the independently calculated high-voltage quadratic root within 2×10⁻⁶ pu; current and `3 I²R` loss agree within 2×10⁻⁵ relative. |
| Swing/governor integration | Initial RoCoF is checked analytically. A 2 s RK4 trajectory at 20 ms agrees with the independent matrix-exponential solution of the linear system within 2×10⁻⁷. |
| IEC 60255 standard-inverse relay | At current/pickup = 2 and TMS 0.1, the independently stated clearing time is 1.062902702 s; pickup and monotonicity cases also pass. |
| Voltage-dependent fault delivery | A resistive three-phase shunt collapses voltage, delivered load falls with voltage, fault heat follows `3 V²/R`, and source power equals delivered load plus losses. |
| RMS event balance | Every 20 ms sample balances wind, storage, oil and link power against served demand and losses within 0.05 MW. |
| Minute energy | Hourly served/requested/wind energy equals the integral of minute results; served never exceeds requested and wind never exceeds availability. |

The tests also exercise source loss and handover: a forming battery carries an island with mainland
exchange at zero; absence of a forming source creates a physical blackout without incrementing solver
failures; HVAC becomes the external AC reference; a healthy HVDC resumes forming duty after HVAC loss;
and a black-start oil unit can energise a partial island. A stable island reduces its shed fraction in
stages. Mid-event save/load preserves controller state and completes the same event.

Protection cases use the native switched network. Tests show that measured current selects a primary
relay, disabling it selects the graded backup, sub-pickup current selects none, and a real alternate
feeder is rejected when its rating is insufficient. A separate case suppresses every overcurrent pickup,
holds a severe fault below 0.5 pu and verifies that the explicitly labelled five-second voltage backup
isolates the faulted line. Fault, auto-reclose, permanent isolation, repair and turbine restart delays
are exercised end to end.

## Conservation, determinism and unsafe input

- The double-entry ledger sums to zero after transfers and multi-day operation. The three-day
  sensitivity baseline leaves a floating residual of −5.17×10⁻⁶ SEK across all accounts.
- Daily per-good reports reconcile opening stock, output, recipe use, trade, household use, liquidation
  and closing stock. The largest full-scale fixture residual is 1.46×10⁻¹¹ in the good's own unit.
- Every water tank reconciles opening volume, pumping, consumption, spill, shortage and closing volume;
  the baseline sensitivity residual is 1.01×10⁻¹⁰ m³.
- POP employment equals the sum of firm job assignments. Monthly population satisfies births, deaths,
  immigration and emigration exactly; split cohorts still age and retire.
- Identical seeds produce identical full-state SHA-256 digests after four hours. Saved random streams,
  event IDs and the settlement watermark prevent divergence or duplicate settlement after retry.
- Save validation rejects unsafe identifiers and solver fields. Compressed histories verify SHA-256,
  declared length and a 64 MB decompression cap; checksum tampering and oversized payload declarations
  fail before a world is rebuilt.

Hourly plans are tested across the boundary and do not step aggregate demand. Actual signed contract
prices drive planning: fixed-price equipment does not move for an unbilled spot-price change. Updating
a retail offer leaves current contracts unchanged and affects eligible renewals. Private facilities cap
borrowing, accrue interest, repay surplus and settle inventory, debt, equity and jobs on exit.

## Automated product coverage

The 69 Python checks cover calendar and event order, independent random streams, weather and wind-field
statistics, ledger and stock identities, labour/capacity-limited production, POP ageing, contracts and
private finance, continuous and discrete loads, minute power/energy balance, OpenDSS switching,
steady-state and RMS references, faults/protection/restoration, islanding, oil and storage life,
construction/impact studies/asset work, idempotent commands and settlements, layered history, save
migration and validation, runtime timing, wake-cache isolation, and the HTTP API including server-side
POP pagination.

The five Chromium workflows cover autonomous startup and all views, parcel inspection and turbine
construction, browser-save reload, phone layout, and the full engineering/retail/history export path.

## Scale and performance

`results/acceptance-scale.json` runs four isolated two-hour worlds, profiles a further ten minutes,
validates each save and then runs two independent workers concurrently. CPU figures are process time per
simulated hour; wall time on a shared host is not used as a portable target.

| Fixture | POPs | Turbines | Buses / branches | CPU ms/sim-h | Solve mean / p95 ms | Peak RSS MiB | Save MB | Failures |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Opening scale | 190 | 54 | 161 / 184 | 651.9 | 2.50 / 3.12 | 48.7 | 0.44 | 0 |
| Medium | 2,000 | 180 | 413 / 436 | 1,061.4 | 5.65 / 7.46 | 57.3 | 1.59 | 0 |
| Large | 6,000 | 360 | 773 / 796 | 1,666.9 | 10.59 / 13.24 | 73.6 | 3.74 | 0 |
| Full object limit | 10,000 | 600 | 1,253 / 1,276 | 2,373.3 | 15.19 / 21.72 | 97.4 | 6.08 | 0 |

All four served 100% of requested energy, preserved 55,300 residents and kept job assignments and goods
accounts consistent. Two worker processes each advanced a four-hour session in 1.559 s wall time with
zero failures.

This is an object-count fixture, not a claim that a calibrated 600-turbine Gutnö system has been
designed. Every synthetic turbine retains a branch and weather response, but availability is uniformly
scaled so total wind matches the 158 MW opening fleet. Extra collectors are 0.3 km at unity power factor
and collector transformers are reinforced. This avoids using the scale check as an impossible 2.1 GW
export/reactive-power scenario. Network planning for such a fleet remains player work.

The retention-capacity fixture fills all 168 hourly, 30 daily, 1,440 selected-object minute and eight
event slots. Its plain archive save is 32,668,958 bytes; zlib/base64/checksummed history reduces it to
9,218,240 bytes (28.2%), below the 12 MB API body limit. These are synthetic storage samples and are
labelled as such in the artifact.

## Browser performance

`results/acceptance-browser.json` loads the full scale save in headless Chromium 154 at 1366×860,
resets instrumentation, and measures four seconds per map. FPS includes animation-frame scheduling.

| World / view | Render mean ms | p95 ms | FPS |
|---|---:|---:|---:|
| Opening island | 1.59 | 4.0 | 59.75 |
| Opening grid | 1.86 | 3.2 | 59.81 |
| 10k POP / 600 turbine island | 6.32 | 9.2 | 59.76 |
| 10k POP / 600 turbine grid | 6.96 | 9.4 | 59.74 |

The 6.08 MB save loaded through the API and client in 635.7 ms. The POP page fetched and rendered 100
rows in 290 ms, then fetched 100 distinct rows on page two. The server reported 9,970 positive-count
rows among 10,000 objects. No page or console errors were captured. This measures headless Chromium on
one machine; it is not a minimum-client specification.

## Sensitivity

`results/acceptance-sensitivity.json` changes one imported coefficient at a time in isolated processes,
using seed 1 and the same first three winter days. Values below are percent changes from the 9,681.48
MWh baseline. They are local short-horizon sensitivities, not annual uncertainty intervals.

| Input variation | Load | Wind | Import | Losses | Peak | PB cash |
|---|---:|---:|---:|---:|---:|---:|
| Demand calibration −10% | −6.109% | 0 | −11.722% | −7.512% | −6.551% | −0.012% |
| Demand calibration +10% | +6.109% | 0 | +12.236% | +9.175% | +6.551% | +0.010% |
| Household heat loss −20% | −4.682% | 0 | −8.781% | −5.774% | −4.551% | −0.014% |
| Household heat loss +20% | +4.682% | 0 | +9.146% | +6.723% | +4.557% | +0.013% |
| Jensen wake coefficient −20% | 0 | −0.243% | +0.280% | −0.023% | 0 | −0.003% |
| Jensen wake coefficient +20% | 0 | +0.201% | −0.242% | +0.013% | 0 | +0.003% |
| Mainland reference price −20% | 0 | 0 | 0 | 0 | 0 | −0.100% |
| Mainland reference price +20% | 0 | 0 | 0 | 0 | 0 | +0.100% |

The unchanged three-day physical result under the price variation is expected: opening customers hold
fixed contracts and the dispatch inputs in this short window do not change. The cash result proves the
price still reaches mainland settlement.

A separate 30-day credit fixture starts with 2 MSEK debt. At 4%, 8% and 12% APR it records respectively
2,131, 4,270 and 6,415 SEK interest; the firm remains operating and repays about 1.55 MSEK in all cases.
A 20 MW / 80 MWh grid-forming battery is 326.6 MSEK and 240 days under declared assumptions; simultaneous
±20% input changes span 261.28–391.92 MSEK and 192–288 days. No probabilities are assigned to the range.

## Autonomous year

The current 365-day seed-1 run is checkpointed every ten days. This section will be replaced with its
complete measured result before the final acceptance commit.

## Findings fixed during acceptance

Opening a branch with OpenDSS `enabled=no` can leave disconnected buses with no admittance to ground and
still return `converged` with absurd losses. Switching now opens both terminals. Every result also passes
finite voltage, loss and source-power plausibility checks, and the regression opens and recloses a radial
branch while checking loss and source balance.

The first current-model annual attempt exposed a statistics boundary: an island could have an energised
set while every reported voltage was at or below the 0.2 pu display filter, leaving `min()` with an empty
sequence. Voltage minimum now records 0 pu for that physical collapse. A direct regression reproduces
the empty-filter condition; the checkpointed year run verifies progress beyond the original day-250
failure before its result is accepted.

That rerun then exposed the reason for the low-voltage state. A severe `l_kal_rom` fault selected the
HVDC upstream overcurrent backup in the prospective study, but converter current limiting kept measured
current below pickup after voltage collapsed. Correctly, the overcurrent integrator did not operate from
the prospective value; incorrectly, no independent line protection cleared the persistent fault. The
model now includes a separately labelled five-second sustained-undervoltage fault backup as a proxy for
the omitted distance/differential layer. The regression recreates the exact HVDC-backup selection and
verifies fault isolation from actual voltage with zero numerical failures. The annual acceptance run is
repeated from day 0 after this fix.

Early scale-fixture trials also clarified that simply cloning 2 km collector cables and voltage-droop
converters creates a different 2.1 GW electrical design with cable charging and overvoltage trips. The
stored fixture therefore declares its compact unity-power-factor collector assumptions and holds total
available wind at the calibrated fleet scale.

## Limits of the evidence

- Gutnö has macro comparisons, not measured feeder, customer, firm or household time series. Public
  island totals do not validate the fictional internal allocation.
- RMS checks validate equations and controlled scenarios. The model has no EMT, harmonic, unbalanced
  or manufacturer-specific validation, and synthetic control/protection settings are not Gotland data.
- One autonomous seed without player action cannot cover the scenario space. Fault rates, extreme
  weather, prolonged islanding and player-built networks need multi-seed campaigns for probability claims.
- The sensitivity run is three winter days and one factor at a time. It does not establish annual
  macroeconomic calibration, parameter interactions or confidence intervals.
- The 10,000-POP/600-turbine case proves bounded storage, rendering and computation under its declared
  controlled fixture. It is not an engineering feasibility study of that installed capacity.
- Browser functional and performance tests use Chromium only. Classroom usability has not yet been
  observed with students.
