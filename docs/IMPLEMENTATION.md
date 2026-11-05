# Agreed first-release scope and implementation record

This record implements the decisions confirmed by the owner after the v0.2 audit.
The source specification is a design input; the decisions below take precedence.

## Accepted decisions

1. Individual turbine steady-state connections; station/farm aggregated RMS event dynamics.
2. Synthetic grid-forming VSC-HVDC; mainland AC reference after HVAC commissioning.
3. Automatic attempted islanding, limited by forming capacity, SOC and protection.
4. Suggested engineering with editable buses, types, routes and station locations.
5. Player-led mainland interconnector construction and expansion, with explicit constraints.
6. Wind and backup oil generators are the first-release generation catalogue.
7. Firms respond to the marginal price in their own actual electricity contract.
8. Finite private credit, interest, repayment and exit; PB investment financing remains explicit.
9. Activity/device-driven demand; forecasts are separate from delivered energy integration.
10. Existing HTML/JavaScript client and independent headless simulation core.
11. Hour/day summaries, selected minute history, event waveforms/action chains and CSV/JSON export.
12. Editable retail policy and new contracts; existing contracts honored; autonomous selection.
13. Physical verification, macro calibration, explicit assumptions and sensitivity analysis.

## Delivery batches

Each batch is checked and committed separately on `codex/development` and pushed to origin.
Completion means executable behavior and validation, not just documentation or a UI placeholder.

- [ ] Production labor/capacity, inventory conservation, elapsed-time protection and request deduplication.
- [x] Contract-consistent planning, retail policy and bounded private finance/exit.
- [ ] Editable engineering, oil backup, player-controlled links and asset lifecycle.
- [ ] Aggregated electrical dynamics, P/Q limits and fault/protection/restoration behavior.
- [x] Versioned module exchanges, persistent layered history and engineering exports (event producer follows).
- [ ] Client controls, layers, object analysis and event inspection.
- [ ] Calibration, conservation/reference checks, sensitivity and scale measurements.

## Validation policy

Keep numerical failures distinct from physical blackouts. Do not describe invented response curves
or steady-state switching as validated RMS dynamics. Preserve old saves with explicit defaults where
possible. Record measured performance rather than promising an unmeasured speedup. Coefficients
without a public source are assumptions and must be visible as such in the model documentation.

## Work log

- Baseline: `bb2ab18`, 26 Python checks passed. Browser checks: 3 passed and one failed due to
  the missing favicon. Audit artifacts: `/workspace/powerbolaget-audit-v02/`.
- Batch 1: labor/capacity-limited industrial throughput, storage-limited recipe production with
  material counters, elapsed-time overload protection, persisted command receipts/client request IDs,
  and favicon. Validation: 30 Python tests and all 4 Chromium game workflows passed.
- Batch 2: immutable signed retail contracts, autonomous renewal, actual-contract load planning,
  calendar-month price index, editable offer UI/API, bounded collateral/payroll credit, interest,
  repayment, credit-constrained input purchases and liquidation/job settlement. Validation: 34 Python
  tests passed; after UI integration the 10 affected Python tests and all 4 browser workflows passed.
- Batch 3a: editable station/bus/transformer/line/collector plans, physical routed length and costs,
  route rendering and engineering dialog; player-led interconnectors with capacity/landing/lead-time
  constraints; legacy scheduled delivery removed; asset lockout, work, cancellation and retirement.
  Validation: 38 Python tests and all 4 browser workflows passed. Oil backup, storage aging and
  electrical event dynamics remain in the following batches.
- Batch 3b: synchronous fuel-oil backup with start/ramp/up/down/fuel/black-start constraints and
  fuel/heat accounting; qualified source handover; fixed-Q/voltage control bounded by P/Q/current
  capability; storage calendar/cycle fade and replacement/retirement. Initial voltage-control gain
  was rejected by regression testing and reduced; controller feedback is persisted. Validation:
  all 42 Python tests and all 4 browser workflows passed.
- Batch 4: versioned intent/forecast/actual exchange envelopes, persisted contiguous settlement
  watermark, saved object history, selected minute recording, hourly/daily object archive and CSV/JSON
  exports with units and retention. Added a browser workflow for engineering, tariff editing, minute
  recording and CSV download. Validation: 46 Python tests and 5 browser workflows passed. Event
  storage/export is ready; the actual RMS event producer belongs to the next batch.
- Batch 5a: fault studies at the receiving end on the actual switched network, graded IEC inverse
  overcurrent pickups and primary/backup selection with timed clearing; physical normally-open
  feeder ties, transfer feasibility and normal-topology restoration replace random load fractions.
  Validation: existing 46 Python tests plus 3 new protection checks passed; browser results below.
