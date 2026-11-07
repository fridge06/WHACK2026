"""Write placeholder inputs to data/mock/ in the PLAN.md 4.1 format.

Usage: python -m pipeline.make_mock [--out DIR] [--seed N]

Reads the teammate's game list (via loaders.load_game_list) and invents everything
else: company symbols, share counts, exchange rates, daily prices and popularity
signals. Symbols are obviously fake (MOCK_P01, MOCK_IDX_1); games with the same
publisher share one invented company. If no game list exists, 25 invented games
are used instead. Output is reproducible for a given seed and game list.

Deliberate problems, so the pipeline and validation have something to catch:
  - a few missing months in one signal for some games (must stay gaps, not zeros)
  - one game with one signal missing entirely (weights must rescale)
  - one game with no data in its launch month (no base month -> excluded)
  - one game whose share price stops mid-window (delisted -> excluded)
Gaps are written as absent rows, never zeros. Every deliberate problem is listed
in expected_issues.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from pipeline.config import ROOT, load_config
from pipeline.dates import window_bounds
from pipeline.loaders import GAME_COLUMNS, load_game_list

N_BENCHMARKS = 3
PRICE_PAD_BEFORE = pd.Timedelta(days=14)  # price rows start this far before each window...
PRICE_PAD_AFTER = pd.Timedelta(days=7)    # ...and end this far after it
SIGNAL_PAD_MONTHS = 2                     # signals run past the window so loaders must trim
DELIST_AFTER_DAYS = 45
DAYS_PER_MONTH = 30.44


def invented_game_list(rng: np.random.Generator, n: int = 25) -> pd.DataFrame:
    """Fallback when there is no game list: n made-up games from 8 made-up publishers."""
    start, end = pd.Timestamp("2015-01-01"), pd.Timestamp("2025-06-30")
    days = rng.integers(0, (end - start).days, size=n)
    return pd.DataFrame(
        {
            "game_id": [f"mock_game_{i:02d}" for i in range(1, n + 1)],
            "name": [f"Mock Game {i:02d}" for i in range(1, n + 1)],
            "publisher": [f"Mock Publisher {chr(65 + int(k))}" for k in rng.integers(0, 8, size=n)],
            "launch_date": [start + pd.Timedelta(days=int(d)) for d in days],
        }
    ).set_index("game_id")


def hype_curve(m: np.ndarray, peak_shift: float, tau: float) -> np.ndarray:
    """Relative interest at month offset m: build-up, peak near launch, then decay to a floor."""
    m = np.asarray(m, dtype=float)
    before = np.exp((m - peak_shift) / 1.3)
    after = 0.1 + 0.9 * np.exp(-(m - peak_shift) / tau)
    return np.where(m < peak_shift, before, after)


def _round(values: np.ndarray, integer: bool) -> np.ndarray:
    return np.round(values) if integer else np.round(values, 2)


def make_companies(publishers: list[str], rng: np.random.Generator) -> dict[str, dict]:
    companies = {}
    for i, pub in enumerate(publishers, 1):
        companies[pub] = {
            "ticker": f"MOCK-{i:02d}",
            "symbol": f"MOCK_P{i:02d}",
            "benchmark": f"MOCK_IDX_{int(rng.integers(1, N_BENCHMARKS + 1))}",
            "beta": float(rng.uniform(0.6, 1.4)),
            # log-uniform share price, from pennies-like to yen-like levels
            "start_price": float(np.exp(rng.uniform(np.log(1), np.log(20000)))),
        }
    return companies


def make_prices(games: pd.DataFrame, companies: dict, rng: np.random.Generator, delisted: dict[str, pd.Timestamp]):
    """Daily closes on weekdays only, with ~1% of weekdays missing (holidays).

    Returns the prices DataFrame.
    """
    start = games["window_from"].min() - pd.Timedelta(days=60)
    end = games["window_to"].max() + pd.Timedelta(days=30)
    bdays = pd.bdate_range(start, end)
    n = len(bdays)

    bench_lr = {}
    bench_close = {}
    for k in range(1, N_BENCHMARKS + 1):
        sym = f"MOCK_IDX_{k}"
        lr = rng.normal(0.0003, 0.01, n)
        bench_lr[sym] = lr
        bench_close[sym] = float(rng.uniform(800, 30000)) * np.exp(np.cumsum(lr))

    company_close = {}
    for pub, co in companies.items():
        launches = games.loc[games["publisher"] == pub, "launch_date"]
        abnormal = np.zeros(n)
        for launch in launches:
            i0 = int(bdays.searchsorted(launch))
            pre = float(rng.normal(0.02, 0.05))     # pre-launch hype drift over ~60 trading days
            post = float(np.clip(rng.normal(0, 0.12), -0.4, 0.4))  # launch effect, mostly within a month
            idx = np.arange(n)
            ramp = np.clip((idx - (i0 - 60)) / 60, 0, 1) * pre
            settle = np.where(idx >= i0, post * (1 - np.exp(-(idx - i0) / 6)), 0)
            abnormal += ramp + settle
        lr = co["beta"] * bench_lr[co["benchmark"]] + rng.normal(0, 0.016, n)
        close = co["start_price"] * np.exp(np.cumsum(lr) + abnormal)
        company_close[co["symbol"]] = close

    # Only write rows each symbol actually needs: the union of its games' padded windows.
    def needed(symbol_games: pd.DataFrame) -> np.ndarray:
        mask = np.zeros(n, dtype=bool)
        for row in symbol_games.itertuples():
            mask |= (bdays >= row.window_from - PRICE_PAD_BEFORE) & (bdays <= row.window_to + PRICE_PAD_AFTER)
        return mask

    frames = []
    for pub, co in companies.items():
        mine = games[games["publisher"] == pub]
        mask = needed(mine) & (rng.random(n) > 0.01)
        if pub in delisted:
            mask &= bdays <= delisted[pub]
        frames.append(pd.DataFrame({"symbol": co["symbol"], "date": bdays[mask], "close": company_close[co["symbol"]][mask]}))
    for sym, close in bench_close.items():
        users = games[games["publisher"].map(lambda p: companies[p]["benchmark"]) == sym]
        if users.empty:
            continue
        mask = needed(users) & (rng.random(n) > 0.01)
        frames.append(pd.DataFrame({"symbol": sym, "date": bdays[mask], "close": close[mask]}))

    prices = pd.concat(frames, ignore_index=True)
    prices["close"] = prices["close"].round(4)
    return prices


def make_signals(games: pd.DataFrame, signal_cfg: dict, cfg_window: dict, rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for gid, g in games.iterrows():
        launch = g["launch_date"]
        launch_month = launch.to_period("M")
        size = float(rng.lognormal(0, 0.6))       # how big this game is overall
        peak_shift = float(rng.choice([0, 0, 1]))  # some games peak the month after launch
        tau = float(rng.uniform(1.5, 4))           # how fast interest fades, in months
        months = np.arange(-cfg_window["months_before"] - SIGNAL_PAD_MONTHS, cfg_window["months_after"] + SIGNAL_PAD_MONTHS + 1)

        for name, s in signal_cfg.items():
            integer = bool(s.get("integer", False))
            if s["granularity"] == "monthly":
                vals = s["scale"] * size * hype_curve(months, peak_shift, tau) * rng.lognormal(0, 0.1, len(months))
                periods = [launch_month + int(m) for m in months]
                fmt = "%Y-%m" if s.get("month_format") == "year_month" else "%Y-%m-01"
                dates = [p.start_time.strftime(fmt) for p in periods]
            else:
                first = (launch_month + int(months[0])).start_time
                last = (launch_month + int(months[-1])).end_time.normalize()
                days = pd.date_range(first, last, freq="D")
                d = (days - launch).days.to_numpy()
                if s.get("starts_at_launch"):
                    days, d = days[d >= 0], d[d >= 0]
                weekend = np.where(days.day_of_week >= 5, 1.15, 1.0)
                vals = s["scale"] * size * hype_curve(d / DAYS_PER_MONTH, peak_shift, tau) * weekend * rng.lognormal(0, 0.15, len(d))
                dates = days.strftime("%Y-%m-%d").tolist()
            vals = _round(vals, integer)
            rows.append(pd.DataFrame({"game_id": gid, "date": dates, "signal": name, "value": vals}))
    return pd.concat(rows, ignore_index=True)


def _month_of(date_str: str) -> pd.Period:
    return pd.Period(date_str[:7], freq="M")


def generate(games: pd.DataFrame, cfg: dict, seed: int) -> dict:
    """Build mock inputs in memory. Returns {"games", "signals", "prices", "issues"}."""
    rng = np.random.default_rng(seed)
    win = cfg["window"]
    signal_cfg = cfg["mock"]["signals"]

    games = games.copy()
    bounds = games["launch_date"].map(lambda d: window_bounds(d, win["months_before"], win["months_after"]))
    games["window_from"] = bounds.map(lambda b: b[0])
    games["window_to"] = bounds.map(lambda b: b[1])

    publishers = list(dict.fromkeys(games["publisher"]))
    companies = make_companies(publishers, rng)

    # Choose which games get deliberate problems (each game gets at most one).
    order = [games.index[i] for i in rng.permutation(len(games))]
    issues: dict = {"excluded": {}, "gaps": {}}
    delisted: dict[str, pd.Timestamp] = {}
    taken: set[str] = set()

    for gid in order:  # delisted: the cutoff must not cut into any sibling game's window
        pub = games.at[gid, "publisher"]
        cutoff = games.at[gid, "launch_date"] + pd.Timedelta(days=DELIST_AFTER_DAYS)
        siblings = games[(games["publisher"] == pub) & (games.index != gid)]
        if (siblings["window_to"] + PRICE_PAD_AFTER < cutoff).all():
            delisted[pub] = cutoff
            issues["excluded"][gid] = f"share price stops {DELIST_AFTER_DAYS} days after launch (delisted)"
            taken.add(gid)
            break
    free = [g for g in order if g not in taken]
    no_base = free[0] if free else None
    missing_signal_game = free[1] if len(free) > 1 else None
    gap_games = free[2:5]

    daily = [n for n, s in signal_cfg.items() if s["granularity"] == "daily"]
    monthly = [n for n, s in signal_cfg.items() if s["granularity"] == "monthly"]
    missing_signal = (daily or list(signal_cfg))[0]
    gap_signal = (monthly or list(signal_cfg))[-1]

    prices = make_prices(games, companies, rng, delisted)
    signals = make_signals(games, signal_cfg, win, rng)

    months = signals["date"].map(_month_of)
    launch_month = signals["game_id"].map(lambda g: games.at[g, "launch_date"].to_period("M"))
    rel = (months - launch_month).map(lambda off: off.n)
    drop = pd.Series(False, index=signals.index)

    if no_base is not None:
        drop |= (signals["game_id"] == no_base) & (rel == 0)
        issues["excluded"][no_base] = "no signal data in the launch month (no base month)"
    if missing_signal_game is not None:
        drop |= (signals["game_id"] == missing_signal_game) & (signals["signal"] == missing_signal)
        issues["gaps"][missing_signal_game] = [f"signal {missing_signal} missing entirely"]
    candidates = [m for m in range(-win["months_before"], win["months_after"] + 1) if m != 0]
    for gid in gap_games:
        gone = sorted(int(m) for m in rng.choice(candidates, size=int(rng.integers(1, 3)), replace=False))
        drop |= (signals["game_id"] == gid) & (signals["signal"] == gap_signal) & rel.isin(gone)
        issues["gaps"][gid] = [f"signal {gap_signal} missing at month offset(s) {gone}"]
    signals = signals[~drop].reset_index(drop=True)

    out = pd.DataFrame(index=games.index)
    out["name"] = games["name"]
    out["short_name"] = games["short_name"] if "short_name" in games else ""
    out["publisher"] = games["publisher"]
    out["city"] = ""
    out["ticker"] = games["publisher"].map(lambda p: companies[p]["ticker"])
    out["price_symbol"] = games["publisher"].map(lambda p: companies[p]["symbol"])
    out["benchmark_symbol"] = games["publisher"].map(lambda p: companies[p]["benchmark"])
    out["launch_date"] = games["launch_date"].dt.strftime("%Y-%m-%d")
    out["steam_appid"] = ""
    out["wikipedia_title"] = ""
    out = out.reset_index()[GAME_COLUMNS]

    prices = prices.sort_values(["symbol", "date"]).reset_index(drop=True)
    prices["date"] = prices["date"].dt.strftime("%Y-%m-%d")
    signals = signals.sort_values(["game_id", "signal", "date"]).reset_index(drop=True)
    return {"games": out, "signals": signals, "prices": prices, "issues": issues}


def write(result: dict, out_dir: Path, seed: int, source: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    result["games"].to_csv(out_dir / "games.csv", index=False)
    result["signals"].to_csv(out_dir / "signals.csv", index=False, float_format="%.10g")
    result["prices"].to_csv(out_dir / "prices.csv", index=False, float_format="%.10g")
    manifest = {"placeholder": True, "seed": seed, "game_list": source, **result["issues"]}
    (out_dir / "expected_issues.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser(prog="python -m pipeline.make_mock", description="Write placeholder inputs.")
    parser.add_argument("--out", type=Path, default=ROOT / cfg["paths"]["mock_dir"])
    parser.add_argument("--seed", type=int, default=cfg["mock"]["seed"])
    args = parser.parse_args(argv)

    list_path = ROOT / cfg["paths"]["game_list"]
    if list_path.exists():
        games = load_game_list(list_path)
        source = cfg["paths"]["game_list"]
    else:
        print(f"No game list at {list_path}; inventing 25 games.", file=sys.stderr)
        games = invented_game_list(np.random.default_rng(args.seed))
        source = "invented"

    result = generate(games, cfg, args.seed)
    write(result, args.out, args.seed, source)

    g, s, p = result["games"], result["signals"], result["prices"]
    print(f"Wrote {len(g)} games, {len(s)} signal rows, {len(p)} price rows to {args.out}")
    for gid, why in result["issues"]["excluded"].items():
        print(f"  expect excluded: {gid}: {why}")
    for gid, notes in result["issues"]["gaps"].items():
        print(f"  expect gaps:     {gid}: {'; '.join(notes)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
