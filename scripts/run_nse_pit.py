"""NSE pairs backtest on a point-in-time universe (SPEC-005).

Survivorship treatment — honest scope:
* The candidate set is WIDENED to include still-listed casualties (YESBANK,
  RCOM, IDEA, ZEEL, SUZLON, RPOWER, PCJEWELLER, JPASSOCIAT, UNITECH,
  ADANIPOWER, COFFEEDAY) and three new sectors with mixed-health members.
* At each formation window, eligibility is decided using ONLY
  formation-window information: >=95% price coverage in the window AND
  top-N per sector by median daily traded value (close x volume). A name
  that was big and liquid in 2019 (YESBANK) enters 2019 books on its 2019
  stature; a name that collapsed later simply drops out of later windows.
* Adding known casualties to the candidate list is itself hindsight, but
  in the bias-REDUCING direction (we add losers, not winners).
* RESIDUAL BIAS, disclosed: names that fully delisted or merged away
  (DHFL, Jet Airways, HDFC Ltd, Mindtree/LTI, Shriram Transport) are
  pruned from the upstream mirror and cannot be included. The corrected
  result is therefore a lower bound on the correction, not the final word.

Mid-sample death handling: if a traded name stops printing, its return
stream goes NaN -> spread P&L freezes at last price (engine fillna(0));
the crash into delisting IS in the data and hits the divergence stop /
beta kill first. Documented approximation.

Same capital (Rs.15L as 5x3L), windows (250/63), costs, and configs as
SPEC-003 so the survivor-vs-PIT comparison is apples-to-apples. Run once.
"""
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from pairstrader.config import PlatformConfig, india_cash_futures_costs
from pairstrader.data.nse_source import NSEEodSource
from pairstrader.backtest.engine import run_backtest
from pairstrader.signals.engines import ZScoreEngine, OUEngine
from pairstrader.performance.metrics import summarize
from scripts.run_nse import SECTORS as BASE_SECTORS

EXTRA: dict[str, list[str]] = {
    "BANKS": ["YESBANK"],
    "POWER": ["RPOWER", "SUZLON", "ADANIPOWER", "JPASSOCIAT"],
    "TELECOM": ["BHARTIARTL", "IDEA", "RCOM"],
    "MEDIA": ["ZEEL", "SUNTV", "PVRINOX"],
    "REALTY": ["DLF", "GODREJPROP", "OBEROIRLTY", "UNITECH", "NBCC"],
}
SECTORS = {sec: list(dict.fromkeys(BASE_SECTORS.get(sec, []) + EXTRA.get(sec, [])))
           for sec in {**BASE_SECTORS, **EXTRA}}
SECTOR_MAP = {sym: sec for sec, syms in SECTORS.items() for sym in syms}
CAPITAL_TOTAL = 1_500_000.0
TOP_N_PER_SECTOR = 6
MIN_FORM_COVERAGE = 0.95


def make_configs() -> dict[str, PlatformConfig]:
    def base() -> PlatformConfig:
        c = PlatformConfig()
        c.costs = india_cash_futures_costs()
        c.backtest.formation_bars = 250
        c.backtest.trading_bars = 63
        c.backtest.capital_per_pair = 300_000.0
        c.discovery.max_pairs = 5
        return c
    b = base()
    s = base()
    s.discovery.require_stability = True
    s.risk.beta_kill_enabled = True
    return {"": b, "+stability": s}


def make_eligibility_fn(volumes: pd.DataFrame):
    def eligibility(form: pd.DataFrame) -> list[str]:
        cov = form.notna().mean()
        candidates = cov[cov >= MIN_FORM_COVERAGE].index
        traded_value = (form[candidates] * volumes.reindex(form.index)[candidates]).median()
        eligible: list[str] = []
        by_sector: dict[str, list[tuple[float, str]]] = {}
        for sym in candidates:
            sec = SECTOR_MAP.get(sym)
            if sec and pd.notna(traded_value[sym]):
                by_sector.setdefault(sec, []).append((float(traded_value[sym]), sym))
        for sec, rows in by_sector.items():
            rows.sort(reverse=True)
            eligible += [sym for _, sym in rows[:TOP_N_PER_SECTOR]]
        return eligible
    return eligibility


def main() -> None:
    src = NSEEodSource(list(SECTOR_MAP), start="2019-01-01", align="ragged")
    prices = src.get_prices()
    volumes = src.get_volumes()
    print(f"PIT candidate set: {len(prices.columns)} symbols (ragged), "
          f"{prices.index[0].date()} -> {prices.index[-1].date()}")

    eligibility = make_eligibility_fn(volumes)
    out: dict = {"engines": {}}
    for suffix, cfg in make_configs().items():
        for engine in (ZScoreEngine(cfg.signal), OUEngine(cfg.signal)):
            result = run_backtest(prices, cfg, engine, sector_map=SECTOR_MAP,
                                  eligibility_fn=eligibility)
            summary = summarize(result, capital_deployed=CAPITAL_TOTAL,
                                bars_per_year=252)
            key = engine.name + "+nse-pit" + suffix
            print(f"\n=== engine: {key} ===")
            print(json.dumps(summary["book"], indent=2))
            print("exit attribution:", {k: (v["count"], round(v["net_pnl"]))
                                        for k, v in summary["exit_attribution"].items()})
            casualties = sorted({t.pair for t in result.trades
                                 if any(leg in {"YESBANK", "RCOM", "IDEA", "SUZLON",
                                                "RPOWER", "ZEEL", "PCJEWELLER",
                                                "JPASSOCIAT", "UNITECH", "ADANIPOWER",
                                                "COFFEEDAY"}
                                        for leg in t.pair.split("/"))})
            print("pairs involving casualty names:", casualties or "none")

            out["engines"][key] = {
                "summary": summary,
                "equity": {str(k.date()): round(float(v), 2) for k, v in result.equity.items()},
                "trades": [asdict(t) for t in result.trades],
                "pair_equity": {c: {str(k.date()): round(float(v), 2)
                                    for k, v in result.daily_pnl[c].dropna().cumsum().items()}
                                for c in (result.daily_pnl.columns if not result.daily_pnl.empty else [])},
                "pair_specs": result.pair_specs,
                "windows": result.windows,
            }

    dest = Path(__file__).resolve().parents[1] / "results.json"
    if dest.exists():
        prior = json.loads(dest.read_text())
        out = {**prior, **out, "engines": {**prior.get("engines", {}), **out["engines"]}}
    dest.write_text(json.dumps(out))
    print(f"\nwrote {dest}")


if __name__ == "__main__":
    main()
