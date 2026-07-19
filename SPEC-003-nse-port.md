# SPEC-003: NSE equities port — sector-restricted pairs, real data, Rs.15L

Target repo: github.com/kumrohit/pairstrader · base: `1afd656` (main HEAD)
Apply: `git am 0001-Port-platform-to-NSE-equities-with-real-data-SPEC-00.patch`, then `python scripts/run_nse.py`.

## Rationale

Cross-country evidence: pairs-trading abnormal returns are most pronounced in emerging markets and in markets with many eligible pairs; short-sale constraints preserve the anomaly. NSE checks all three, and single-stock futures let us take the short leg most participants can't.

## Changes

1. **`data/nse_source.py`** — real NSE EOD via the eod2_data GitHub mirror: split/bonus-adjusted daily closes since 1995, keyless, cached 24h, thin-coverage symbols dropped with a warning (LTIM and TATAMOTORS drop on post-merger/demerger history breaks).
2. **Sector restriction** — `discover_pairs(..., sector_map=)` considers only same-sector candidates; `run_backtest` passes it through. Backward compatible (default None = old behavior).
3. **`india_cash_futures_costs()`** — preset for the Rs.15L-feasible structure (long cash, short futures): ~11.5bp per leg per side incl. slippage, funding field repurposed as futures roll drag (0.3 on 2x notional = 0.6%/yr on the futures leg). Derivation in docstring; statutory rates flagged for periodic re-verification.
4. **Trading-calendar metrics** — `summarize(..., bars_per_year=252)`; default 365 preserved so crypto results are untouched.
5. **`scripts/run_nse.py`** — 60 liquid F&O names in 10 static sectors, 2019–2026, 250/63 trading-day windows, capital 15L as 5 x 3L pair slots (deployment math and lot-size caveat in the docstring), baseline vs +stability, both engines, merge-safe results.json write, per-pair short-leg notionals printed for lot verification.

## Results of the single run (real data, 2019-01 → 2026-07, ~28 windows)

| engine | net (Rs.) | Sharpe | maxDD | trades | win% | RoC |
|---|---|---|---|---|---|---|
| zscore+nse | +543,622 | 0.75 | −132,618 | 206 | 77.1 | +36.2% |
| ou+nse | +643,951 | 0.91 | −121,672 | 213 | 60.7 | +42.9% |
| zscore+nse+stability | +139,199 | 0.67 | −53,239 | 39 | 60.5 | +9.3% |
| ou+nse+stability | +53,029 | 0.23 | −108,980 | 40 | 47.4 | +3.5% |

Attribution (z-score baseline): converged +12.9L / stopped −5.4L / timed-out −1.3L / window-end −0.8L — the inverse of crypto. The stability filter reduces both risk and return; on this universe its cost exceeds its benefit.

## Caveats (spelled out in STRATEGY.md §8d)

Survivorship bias is the binding one: today's F&O list projected back to 2019 — returns overstated by unknown magnitude; a point-in-time eligibility universe is the SPEC-004 candidate before any live decision. Also: static sector map, cash-leg dividends unmodeled (conservative), lot granularity reported but not enforced.

## Acceptance + regression checks

1. `run_nse.py` completes on a fresh clone (network to raw.githubusercontent.com required); universe ≥ 55 symbols, ≥ 1,800 trading days.
2. All four `+nse` engine keys present; exit-attribution nets sum to book net (±1) for each.
3. Crypto engine keys (`zscore`, `ou`, `*+stability`, `*+linked`) survive the merge-safe write unchanged.
4. Crypto results regression: `zscore` book net still −46,726.66 (bars_per_year default untouched).
5. Dashboard renders all engine variants via the existing toggle with no dashboard changes.
