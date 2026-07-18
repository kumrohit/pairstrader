# Pairs Trading Platform (crypto v1)

**New here? Read [STRATEGY.md](STRATEGY.md)** — a full plain-language + math walkthrough of what the platform does and why.

Walk-forward pairs trading research and performance-tracking platform. Design follows the empirical literature: cointegration-based selection, formation/trading window separation, explicit cost modeling, and drawdown-first performance reporting.

## Architecture

- `pairstrader/config.py` — every economic assumption (fees, slippage, funding, filters, windows) in one auditable place
- `pairstrader/data/loader.py` — `DataSource` interface; `CSVDataSource` for real data, `SyntheticCryptoSource` with known ground truth for engine validation
- `pairstrader/discovery/pairs.py` — correlation pre-filter → Engle-Granger (OLS hedge ratio + ADF on residual) → half-life filter → ranked pair book
- `pairstrader/signals/engines.py` — pluggable `SignalEngine` interface; ships `ZScoreEngine` (rolling bands) and `OUEngine` (OU fit on formation spread, static stationary-sigma bands)
- `pairstrader/backtest/engine.py` — non-overlapping walk-forward; per-leg fee + slippage on every execution, funding drag while held; full trade ledger with exit reasons
- `pairstrader/performance/metrics.py` — Sharpe, Sortino, max drawdown, convergence stats, gross-vs-net cost attribution, per-pair breakdown
- `pairstrader/api/server.py` + `dashboard.html` — FastAPI tracker with equity curve, cost waterfall, per-pair ledger, engine toggle

## Usage

```bash
pip install numpy pandas statsmodels fastapi uvicorn
python scripts/run_demo.py                       # validate on synthetic universe, writes results.json
uvicorn pairstrader.api.server:app --reload      # dashboard at http://127.0.0.1:8000
```

Real data: point `CSVDataSource` at a wide CSV (timestamp, one close column per symbol), or implement `DataSource.get_prices()` over an exchange client.

### macOS setup gotchas

- If `python scripts/run_demo.py` fails with `ModuleNotFoundError` despite `pip list` showing the package installed, your shell likely has `python` aliased to the system interpreter, which shadows an activated venv. Invoke the venv's interpreter directly (e.g. `.venvpairs/bin/python scripts/run_real.py`) or fix the alias.
- If `run_real.py` fails with `SSL: CERTIFICATE_VERIFY_FAILED` while fetching Coin Metrics/Binance data, your Python was installed via the python.org macOS installer, which ships an unpopulated CA bundle. Run `/Applications/Python\ 3.x/Install\ Certificates.command` once to fix it for that interpreter.

## Design decisions (and why)

- Hedge ratio, z-score seed, and OU parameters are frozen at formation-window end — the trading window is genuinely out-of-sample
- Costs are structural, not a post-hoc haircut: 4 executions per round trip, plus conservative funding drag on gross notional while positions are open
- Exits: convergence (|z| ≤ exit), divergence stop (|z| ≥ stop), and time stop (max holding) — the two stop types are where pairs books die
- Discovery re-runs every window: pairs that lose cointegration drop out of the book automatically
- The synthetic universe includes independent random walks as negative controls; expect occasional spurious pairs at ADF p < 0.05 (multiple-testing) — this is a feature of the validation, and the reason a live version should add a second confirmation (Johansen, or a rolling-stability requirement)

## Caveats

- Synthetic-universe results validate the machinery, not the edge: spreads there are mean-reverting by construction, so Sharpe/win rates are upper bounds with no bearing on live performance
- Realistic expectations on real crypto data, per the literature: modest net edge concentrated in high-volatility regimes, with material drawdowns from divergence risk
- Funding is modeled as a constant drag; on real perp data, replace with the actual funding-rate series per symbol (it can be a P&L source, not just a cost)
- No tax modeling yet: Indian crypto tax treatment depends on instrument and venue — add to `CostConfig` once the venue is fixed

## Free data sources (integrated)

- `CoinMetricsSource` — Coin Metrics community data: per-asset daily USD reference rates as CSVs on GitHub, no key, no rate limits, history from genesis. Caveat: the community tier only carries full history for some assets (SOL/AVAX/ATOM/NEAR/FIL come back as 7-day stubs); the adapter detects and drops thin-history columns automatically. 15 of the 20 requested majors survive with full history from 2022.
- `BinanceSource` — Binance public klines REST endpoint: keyless for market data, full per-venue history, daily or intraday bars, paginated at 1000 candles/request with polite throttling. Use on your own machine (this sandbox can't reach exchange APIs); both adapters cache locally so repeated backtests don't re-download.
- Also evaluated: CoinGecko free tier (10K calls/month but historical queries capped at 365 days — too short for formation windows), CoinMarketCap free tier (no historical OHLCV), CryptoDataDownload (good bulk CSVs, but manual downloads rather than an API).

Run on real data: `python scripts/run_real.py` (writes the same results.json the dashboard reads).

## Real-data baseline (read this before tuning anything)

Naive v1 configuration on 15 majors, 2022–2026, 14 walk-forward windows, full costs: **both engines lose money** (z-score net −47k on 69k capital, Sharpe −1.2; OU net −34k, Sharpe −0.9). The diagnostic is the valuable part: trades that converged made **+51k**, while stopped and timed-out trades lost **−90k+** — in-sample cointegration among crypto majors frequently breaks out-of-sample, and divergence losses swamp convergence gains. This is precisely the Do & Faff / ETF-stability finding reproduced independently, and it is why the roadmap's next item is selection quality (rolling cointegration stability, Johansen confirmation, beta-drift monitoring), not threshold tuning. Do not fit thresholds to this sample to force the number positive — that is data snooping, and the platform exists to prevent it.


- Phase 2: rolling cointegration-stability monitor, paper-trading loop writing the same results schema, funding-rate series ingestion
- Phase 3: copula mispricing-index engine, Johansen confirmation, clustering-based universe expansion
