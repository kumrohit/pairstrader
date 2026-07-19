# SPEC-004: dashboard v2 — tabbed views, global filters, client-side scoping

Target repo: github.com/kumrohit/pairstrader · base: `31d29b4` (main HEAD)
Apply: `git am 0001-Dashboard-v2*.patch`. Frontend-only — no Python changes, no rerun needed; works against the committed results.json.

## Problem

v1 showed every panel at once with no scoping: no way to look at one walk-forward window, one pair, or filter the blotter.

## Design

Single global filter state `{engine, window, pair, exit-reason}` drives four tabs; every panel recomputes client-side against the active scope (all inputs already exist in results.json).

- **Filter bar** (persistent): engine, window (`all` or one trading window), pair, reset. A scope line always states exactly what you're looking at.
- **Overview**: stat cards, equity curve, gross→net waterfall, exit attribution — all scoped. Equity slices to the window and rebases to 0 at scope start.
- **Pairs**: aggregated ledger (sortable columns), click-to-focus a pair → detail panel with scoped pair equity and formation specs (now including β-drift) for the scoped windows only.
- **Trades**: full blotter, sortable on any column, exit-reason chips as one-click filters, capped at 400 rendered rows.
- **Windows**: per-window table (dates, book composition, trade count, closed net), click-to-focus a window — which then scopes every other tab.

Two P&L bases coexist and the footnote says so: curves/Sharpe/drawdown use daily mark-to-market; waterfall/attribution/tables use closed-trade sums. Small edge-of-scope differences are expected, not bugs.

Sharpe annualization is engine-aware client-side: 252 for `+nse` variants, 365 otherwise.

## Verification (headless, in-repo)

`node --check` passes; a DOM-stubbed functional run drives all four views across filter combinations: window scoping verified against trade dates; pair+window equity slices rebase to 0; full-scope recomputed Sharpe and maxDD match Python-stored values exactly (0.75 / −132,618 for zscore+nse); closed-trade net ties to stored book net; empty scopes render without throwing. Served via FastAPI, all four tab containers present in the response.

## Acceptance checks

1. Open dashboard → four tabs render; engine dropdown lists all 10 variants.
2. Select a window in Windows tab → Overview stats change and scope line updates; reset restores.
3. Pairs tab: click a pair → detail with specs limited to scoped windows; click again to unfocus.
4. Trades tab: sort by Net descending; click a reason chip → row count matches chip count.
5. No console errors on engines lacking a filtered pair's data (empty-scope message shown instead).
