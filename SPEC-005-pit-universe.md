# SPEC-005: point-in-time universe — survivorship correction

Target repo: github.com/kumrohit/pairstrader · base: `47425d7` (main HEAD)
Apply: `git am 0001-Point-in-time-universe-correction-SPEC-005.patch`, then `python scripts/run_nse_pit.py`.

## Data feasibility (probed first)

The eod2 mirror retains still-listed casualties (YESBANK, RCOM, IDEA, ZEEL, SUZLON, RPOWER, PCJEWELLER, JPASSOCIAT, UNITECH, ADANIPOWER, COFFEEDAY) but prunes fully delisted/merged names (DHFL, Jet Airways, HDFC Ltd, Mindtree, LTI, Shriram Transport — all 404). Full survivorship correction is impossible from this source; a partial, bias-reducing correction is implemented, with the residual disclosed.

## Changes

1. **`NSEEodSource(align="ragged")`** — keeps thin/gappy histories instead of dropping them; `get_volumes()` returns aligned volumes. Strict mode (default) unchanged.
2. **`run_backtest(..., eligibility_fn=)`** — optional per-window universe hook, called on formation data only. None = old behavior.
3. **`scripts/run_nse_pit.py`** — 76-name candidate set (SPEC-003 universe + casualties + TELECOM/MEDIA/REALTY sectors), eligibility = ≥95% formation coverage AND top-6 per sector by formation-window median traded value. Same capital (15L as 5×3L), windows, and costs as SPEC-003. Mid-sample death handling documented (crash is in the data and hits stops; post-delisting P&L freezes).

## Results of the single run (vs SPEC-003 survivor universe)

| engine | net | Sharpe | maxDD | trades |
|---|---|---|---|---|
| zscore survivor → PIT | +543,622 → **+266,772** | 0.75 → **0.25** | −132,618 → **−510,136** | 206 → 203 |
| ou survivor → PIT | +643,951 → **+447,599** | 0.91 → **0.44** | −121,672 → **−282,960** | 213 → 231 |
| zscore+stability → PIT | +139,199 → **−56,190** | 0.67 → −0.19 | | |
| ou+stability → PIT | +53,029 → **−221,804** | 0.23 → −0.72 | | |

Casualty pairs verifiably traded: AXISBANK/YESBANK, IDEA/RCOM, DLF/UNITECH, GODREJPROP/UNITECH, ZEEL/PVRINOX, NTPC/ADANIPOWER, and the SUZLON/RPOWER/JPASSOCIAT complex.

**Verdict:** roughly half the survivor-run profit was survivorship bias. The unconditional result — marginal positive net, Sharpe 0.25–0.44, drawdown up to a third of capital — is not investable at Rs.15L retail assumptions. Limitations of the correction (lower-bound residual bias; small added sectors admit penny-stage names a real F&O liquidity floor would exclude) are documented in STRATEGY.md §8e; a traded-value floor is flagged as a future run-once refinement, not applied retroactively.

## Acceptance + regression checks

1. `run_nse_pit.py` completes; four `+nse-pit` engine keys added; attribution nets sum to book nets (±1).
2. All ten prior engine keys survive the merge-safe write; `zscore` (crypto) still −46,726.66 and `zscore+nse` (survivor) still +543,621.96.
3. PIT trade ledgers contain pairs with casualty legs (list above non-empty).
4. `NSEEodSource` default (strict) behavior unchanged: rerunning `run_nse.py` reproduces SPEC-003 outputs.
5. Dashboard: `+nse-pit` variants selectable; Sharpe annualization treats them as 252-day (key contains `+nse`).
