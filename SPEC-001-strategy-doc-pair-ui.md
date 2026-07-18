# Spec: strategy doc + exit attribution + pair-detail UI

Target repo: github.com/kumrohit/pairstrader · base: `a3f9e61` (main HEAD)
Preferred application: `git am 0001-Add-strategy-doc-exit-reason-attribution-and-pair-de.patch` — everything below is already implemented in the patch. This spec is the reference for review, or for Claude Code to re-implement if the patch doesn't apply cleanly.

## 1. STRATEGY.md (new file, repo root)

Full methodology walkthrough so the platform is not a black box: pipeline diagram; discovery math (correlation pre-filter, OLS hedge ratio on log prices, ADF on residual spread, AR(1) half-life formula, ranking); both signal engines with formulas (rolling z-score vs OU fit with frozen μ and stationary σ); the exit state machine (converge 0.5 / stop 3.5 / time-stop 45d, with re-entry block after stops); cost model arithmetic (≈32bp round trip + funding drag); walk-forward discipline (everything frozen at formation); the real-data findings and the explicit prohibition on tuning thresholds to the 2022–26 sample. Link it from the top of README.md.

## 2. Exit-reason attribution (engine + metrics)

- `signals/engines.py` — `_band_positions` records `{bar_index: reason}` for every close, reason ∈ {converged, stopped, timed_out}, attached as `pos.attrs["exit_reasons"]`. No interface change: still returns a Series.
- `backtest/engine.py` — ledger reads `pos.attrs.get("exit_reasons", {})`; `Trade.exit_reason` now carries the true reason instead of collapsed "closed"; `Trade.converged` becomes `reason == "converged"` (previously inferred from P&L sign — wrong for trades that converged at a small net loss after costs).
- `performance/metrics.py` — `summarize()` gains a top-level `exit_attribution` dict: per reason, `{count, net_pnl, gross_pnl, avg_holding_days}`.

## 3. Per-pair equity export (both scripts)

`run_demo.py` and `run_real.py` add to each engine's results blob:
`"pair_equity": {pair: {date: cumulative net pnl}}`, from `result.daily_pnl[col].dropna().cumsum()`.

## 4. Dashboard (`api/dashboard.html`)

Keep the existing design system (palette, IBM Plex Mono / Space Grotesk, panel style). Add:

- **Exit-attribution panel** ("Where P&L dies"): one chip per exit reason with net P&L (green/red), trade count, avg holding days, plus a legend line explaining each reason.
- **Clickable per-pair ledger**: rows select a pair (highlight with teal outline); the net-share bar is now scaled to max |net| across pairs and colored by sign (previous version broke when book net was negative).
- **Pair-detail panel** (hidden until a pair is selected; smooth-scrolls into view): summary chips (net P&L, trades, win rate, converged/total exits, windows selected); pair equity curve (reuse the line-chart function, parameterized by element id and dimensions, area tint by sign of final value); formation-spec table per window (window start, β, ADF p, half-life, correlation); full trade table (entry, exit, direction, days held, gross, costs, net, exit reason). "Back to book" button clears selection.
- **Robustness fixes** while in there: waterfall handles negative gross (baseline at zero line, cost note switches wording); cost-drag stat falls back to absolute costs when gross ≤ 0.

## 5. Acceptance checks

1. `python scripts/run_real.py` completes; results.json contains `exit_attribution` and `pair_equity` for both engines.
2. Sum of `exit_attribution[*].net_pnl` equals book `net_pnl` (±rounding).
3. Dashboard: engine toggle works; clicking LTC/XLM shows its equity, ≥1 formation spec row, and its trades; back button returns to book view.
4. No trade carries `exit_reason == "closed"` anymore (only converged/stopped/timed_out/window_end).
