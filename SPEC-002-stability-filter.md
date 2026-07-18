# SPEC-002: formation stability filter + beta-drift kill switch

Target repo: github.com/kumrohit/pairstrader · base: `0479acc` (main HEAD)
Apply: `git am 0001-Add-formation-stability-filter-and-beta-drift-kill-s.patch`

## Motivation (from baseline diagnostics)

Baseline attribution: converged +61k / stopped −50k / timed-out −35k, with stopped trades averaging 6.2 days held — pairs that break, break fast. Two structural interventions, both changing *selection and monitoring*, neither touching signal thresholds.

## 1. Formation-time stability filter (`discovery/pairs.py`, `config.py`)

New `DiscoveryConfig` fields: `require_stability` (default False — baseline behavior unchanged), `stability_subwindows=3`, `stability_half_life_max_days=45`, `stability_beta_drift_max=0.25`.

`stability_check()`: split formation into K equal segments; on each, using the full-window α/β spread, require (a) AR(1) mean reversion present with segment half-life ≤ 45d, and (b) segment-re-estimated β within 25% of full-window β. `PairSpec` gains `beta_drift` (max segment deviation), exported in `pair_specs`.

**Disclosed design revision:** v1 required per-segment ADF p ≤ 0.10; with ~120 obs per segment ADF is underpowered and zero pairs passed in any window. Rejected as degenerate before reading P&L; v2 (above) fixed a priori and run once.

## 2. Trading-time beta-drift kill (`portfolio/risk.py`, `backtest/engine.py`, `config.py`)

New `RiskConfig`: `beta_kill_enabled` (default False), `beta_kill_window=60`, `beta_kill_tol=0.30`. `beta_drift_kill()` re-estimates β on a rolling window (seeded with formation tail), force-closes on first breach with new exit reason `beta_break`, and locks the pair out for the rest of the window. Preserves/extends the engine's `exit_reasons` attrs.

## 3. Comparison harness (`scripts/run_real.py`) and dashboard

`run_real.py` runs both configurations — baseline and `+stability` (filter + kill on) — for both engines into one results.json (`zscore`, `ou`, `zscore+stability`, `ou+stability`); the dashboard engine toggle picks them up automatically. Dashboard: `beta_break` added to exit-attribution order and legend.

## 4. Results of the single sanctioned run (2022–2026, 15 majors, daily)

| engine | net | Sharpe | maxDD | trades | pairs/window |
|---|---|---|---|---|---|
| zscore | −46,727 | −1.17 | −48,121 | 189 | 6.9 |
| ou | −33,511 | −0.92 | −36,274 | 137 | 6.9 |
| zscore+stability | −2,574 | −0.79 | −2,574 | 9 | 1.3 |
| ou+stability | −3,829 | −0.91 | −4,508 | 9 | 1.3 |

The filter removes ~95% of absolute loss by removing most trading; break losses per trade shrink ~60% via the kill switch; risk-adjusted performance stays negative. Verdict and implications documented in STRATEGY.md §8b. No threshold tuning performed.

## 5. Acceptance + regression checks

1. Baseline engines reproduce prior run exactly: zscore net −46,726.66, Sharpe −1.17, 189 trades, win% 52.6; ou net −33,511.16 (regression guard).
2. All four engines: exit-attribution net sums equal book net (±1).
3. `+stability` runs contain `beta_break` exits; no trade carries reason `closed`.
4. With `require_stability=False` and `beta_kill_enabled=False`, discovery output is byte-identical to pre-patch behavior (defaults off).
5. `pair_specs` entries in `+stability` results include non-null `beta_drift`.
