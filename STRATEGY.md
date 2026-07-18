# Strategy Document — Pairs Trading Platform

This document explains exactly what the platform does, step by step, with the math and the reasoning. After reading it, nothing in a backtest run should be a black box. File references point at the code that implements each step.

## 1. The idea in one paragraph

Two assets whose prices are tied together by a common economic driver (two large-cap L1 tokens, a wrapped asset and its underlying) drift apart temporarily and come back together. We measure that tie on past data (the *formation window*), define "apart" statistically, and when the gap gets unusually wide we sell the expensive leg and buy the cheap one, sized so the position has no net market exposure. Profit comes from the gap closing, not from the market going up. The whole edifice rests on one assumption — the historical relationship keeps holding — and every loss mechanism in this strategy is some version of that assumption failing.

## 2. Pipeline overview

```
prices ──► pair discovery ──► hedge ratio & spread ──► signal engine ──► positions
             (formation)          (formation)            (trading)
                                                              │
results.json ◄── performance metrics ◄── cost model ◄── P&L engine
```

Each run splits history into non-overlapping walk-forward windows: 365 days of formation, then 90 days of trading, then roll forward 90 days and repeat (`config.BacktestConfig`). Everything estimated on the formation window is **frozen** before the trading window starts. Nothing in the trading window is used to select pairs, fit hedge ratios, or calibrate thresholds for that same window — this is the platform's core anti-overfitting discipline.

## 3. Pair discovery (`discovery/pairs.py`)

For every pair (A, B) in the universe, on formation data only:

**Step 1 — correlation pre-filter.** Compute correlation of log prices; discard pairs below 0.80. This is purely a cost saver: cointegration testing every pair is O(N²) and most pairs are hopeless.

**Step 2 — hedge ratio by OLS.** Regress log P_A on log P_B:

    log P_A(t) = α + β · log P_B(t) + ε(t)

β is the *hedge ratio*: how many units of B offset one unit of A. The *spread* is the residual:

    S(t) = log P_A(t) − α − β · log P_B(t)

Working in logs makes the spread a relative-value measure (percentage terms) and makes β stable across price scales.

**Step 3 — stationarity test (Engle-Granger).** Run an Augmented Dickey-Fuller test on S(t). The null hypothesis is "S has a unit root" (i.e. the spread wanders off and never has to come back). We require p < 0.05 to reject it. Passing means the spread has been mean-reverting *in the formation sample* — no more than that.

**Step 4 — half-life filter.** Fit the AR(1) regression ΔS(t) = a + b·S(t−1) + e(t). If b < 0 the spread pulls back toward its mean, and the half-life of a deviation is

    HL = −ln(2) / ln(1 + b)

We require 1 ≤ HL ≤ 30 days. Too fast is microstructure noise we can't monetize at daily bars; too slow ties up capital and gives the relationship more time to break.

**Step 5 — ranking.** Survivors are ranked by ADF p-value; the top 10 form the book for that window.

**Known weakness (measured, not hypothetical):** with ~100+ candidate pairs tested per window at p < 0.05, a few *spurious* pairs pass by chance, and genuinely cointegrated-in-sample pairs frequently break out-of-sample. The real-data run showed converged trades earning +51k while stopped/timed-out trades lost −90k+. Selection stability — not thresholds — is the binding constraint. See §8.

## 4. Signal engines (`signals/engines.py`)

Both engines map the trading-window spread to a target position in {−1, 0, +1} *spread units*. +1 (long spread) = long A, short β·B; −1 = the reverse. Both share the same exit state machine; they differ only in how they standardize the spread.

**Z-score engine.** Standardize with a 60-day rolling mean and standard deviation (seeded with the last 60 formation days so day one of trading has a valid z-score):

    z(t) = (S(t) − mean_60(t)) / sd_60(t)

**OU engine.** Fit an Ornstein-Uhlenbeck process to the *formation* spread — a continuous-time model of mean reversion, dS = κ(μ − S)dt + σ dW — via the same AR(1) regression (κ = −b, μ = a/κ), and compute the *stationary* standard deviation σ_stat = σ_ε / √(κ(2−κ)). Then

    z(t) = (S(t) − μ) / σ_stat

with μ and σ_stat frozen from formation. The practical difference: the z-score engine adapts its idea of "normal" as the trading window unfolds (self-healing if the level shifts, but slower to flag a break); the OU engine holds the formation-window yardstick fixed (purer out-of-sample test, harsher when the level genuinely moves).

## 5. Entry and exit rules (the state machine)

From flat: enter short spread when z ≥ +2.0, long spread when z ≤ −2.0.
While in a position, three exits, checked every bar:

- **Convergence** (the good one): |z| ≤ 0.5 — the gap closed; take profit.
- **Divergence stop** (the insurance): |z| ≥ 3.5 — the gap blew out instead; assume the relationship broke and cut. After a stop, re-entry on the same side is blocked until z re-enters the entry band, so we don't re-buy a broken pair on the next bar.
- **Time stop**: 45 days held — the trade isn't converging; capital and break-risk argue for release.

All thresholds live in `config.SignalConfig`. They are deliberately literature-standard (2.0/0.5 bands are the Gatev convention), not optimized — see §8 for why we refuse to tune them on the current sample.

## 6. P&L and cost model (`backtest/engine.py`)

Daily P&L of one spread unit = notional × (r_A − β·r_B) where r are daily log returns, position lagged one bar (you trade on the signal, you earn from the next bar). Costs, applied explicitly:

- **Execution**: (taker fee 5bp + slippage 3bp) × both legs × every entry and exit — a full round trip is 4 executions, ≈ 32bp of notional.
- **Funding**: 8% annualized drag on gross notional while the position is open, as a conservative stand-in for perp funding (real funding can be earned as well as paid; the platform assumes it hurts until fed a real funding series).

Every trade is written to a ledger with direction, dates, holding days, gross, costs, net, and exit reason. The gross → costs → net decomposition is a first-class output because, per the empirical literature, costs are routinely the difference between a strategy that works on paper and one that works.

## 7. Performance metrics (`performance/metrics.py`)

Book- and pair-level: net/gross P&L, cost share of gross, annualized Sharpe and Sortino (365-day year — crypto never closes), maximum drawdown, win rate, holding-time distribution, and exit-reason attribution. Max drawdown gets equal billing with Sharpe deliberately: pairs returns partly compensate for divergence risk, and the drawdown is where that risk lives.

## 8. What the real-data baseline taught us

15 majors, 2022–2026, 14 windows, full costs: both engines net negative (Sharpe −0.9 to −1.2). Attribution: convergence exits were solidly profitable; stop and time-stop exits destroyed roughly twice what convergence earned. Interpretation: the signal logic works when the relationship holds; the *selection* passes too many relationships that don't keep holding. The sanctioned next steps, in order:

1. Rolling-stability requirement: a pair must pass the ADF test on sub-windows of formation, not just the full window
2. Johansen test as a second, independent cointegration confirmation
3. Beta-drift monitor: recompute β on a rolling basis in the trading window; exit if it walks away from the formation estimate

What is *not* sanctioned: re-fitting entry/exit/stop thresholds on this same 2022–2026 sample until the total turns positive. With 6 free parameters and one sample, that is curve fitting, and the walk-forward design exists precisely to keep us honest about it. When a selection improvement is implemented, the verdict comes from the untouched holdout convention: freeze the change, run once, read the number.

## 8b. Stability filter results (SPEC-002)

The filter was implemented as specified in §8 and run once. Two candid findings:

**Design revision, disclosed:** v1 demanded a significant ADF test on each formation sub-window; with ~120 observations ADF is so underpowered that zero pairs passed in any window — degenerate by inspection, before any P&L was read. v2 keeps ADF at the full window and requires per-segment *estimator stability* instead (mean reversion present with half-life ≤ 45d per segment, β-drift ≤ 25%). Parameters were fixed before the run; the run was performed once.

**Outcome:** the filter shrinks the book from 6.9 to 1.3 pairs/window (189 → 9 trades). Absolute losses fall ~95% (z-score net −47k → −2.6k) and per-trade break losses shrink (the trading-time β-kill cuts broken pairs at ≈ −430/trade vs ≈ −1,100/trade for the baseline's 3.5σ stops), but Sharpe stays negative. Even 3-segment-stable pairs mostly broke out-of-sample (β-break was the modal exit). Interpretation: among these 15 majors at daily bars, 2022–2026, cross-asset cointegration is not stable enough to trade with distance/cointegration tools — consistent with the post-2009 decay literature. The platform's verdict machinery worked; the universe/frequency is the problem. Sanctioned next directions: economically-linked pairs (wrapped/staked variants via Binance data), intraday bars, funding-rate P&L, and the copula engine — each changes the information set, not the thresholds.

## 9. Parameter reference

Every economically meaningful number lives in `pairstrader/config.py`: costs (`CostConfig`), selection filters (`DiscoveryConfig`), signal thresholds (`SignalConfig`), window sizes and capital (`BacktestConfig`). If a behavior of the platform surprises you, the explanation is in this document or in that one file.
