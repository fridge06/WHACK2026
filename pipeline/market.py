"""Daily % change in market value, the market-implied path, and the verdict (PLAN.md 5.2, 5.3).

Market value is shown as % change since launch. With the share count constant over
the window, that equals the % change in the share price, so no share counts or
exchange rates are needed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pipeline.errors import GameDataError

PCT_DECIMALS = 4     # per-day values; the verdict is rounded to 2


def verdict_phrase(day: int) -> str:
    if day == 7:
        return "In its first week"
    if day == 30:
        return "In its first month"
    return f"In its first {day} days"


def carry_forward(closes: pd.Series, days: pd.DatetimeIndex, max_gap_days: int, label: str) -> tuple[np.ndarray, np.ndarray]:
    """Closes on every calendar day in `days`, carrying the last close forward.

    closes: indexed by trading date, sorted. Returns (values, traded_that_day).
    Raises GameDataError if there is no close on or before the first day, or if any
    gap between closes (including up to the last day) exceeds max_gap_days.
    """
    start, end = days[0], days[-1]
    before = closes[closes.index <= start]
    if before.empty:
        raise GameDataError(f"{label}: no close on or before {start.date()}")
    used = closes[(closes.index >= before.index[-1]) & (closes.index <= end)]

    points = used.index.append(pd.DatetimeIndex([end]))
    gaps = points[1:] - points[:-1]
    worst = int(np.argmax(gaps.days)) if len(gaps) else 0
    if len(gaps) and gaps.days[worst] > max_gap_days:
        raise GameDataError(
            f"{label}: no close for {gaps.days[worst]} days after {points[worst].date()} "
            f"(limit {max_gap_days}); missing data or delisted"
        )

    values = used.reindex(used.index.union(days)).ffill().reindex(days).to_numpy(dtype=float)
    return values, days.isin(used.index)


def _require_text(game: pd.Series, field: str) -> str:
    value = game.get(field)
    value = "" if value is None or (isinstance(value, float) and np.isnan(value)) else str(value).strip()
    if not value:
        raise GameDataError(f"missing {field}")
    return value


def compute_market(
    game: pd.Series,
    closes_by_symbol: dict[str, pd.Series],
    window_from: pd.Timestamp,
    window_to: pd.Timestamp,
    verdict_day: int,
    max_gap_days: int,
) -> dict:
    """Market series and verdict for one game. Raises GameDataError on data problems.

    Returns {"market": [...], "verdict": {...}, "anchor": Timestamp}.
    """
    launch = pd.Timestamp(game["launch_date"]).normalize()
    symbol = _require_text(game, "price_symbol")
    bench_symbol = _require_text(game, "benchmark_symbol")
    for sym, what in ((symbol, "share price"), (bench_symbol, "benchmark")):
        if sym not in closes_by_symbol:
            raise GameDataError(f"no {what} data for symbol {sym}")

    days = pd.date_range(window_from, window_to, freq="D")
    close, trading = carry_forward(closes_by_symbol[symbol], days, max_gap_days, f"share price {symbol}")
    bench, _ = carry_forward(closes_by_symbol[bench_symbol], days, max_gap_days, f"benchmark {bench_symbol}")

    traded_by_launch = np.flatnonzero(trading & (days <= launch))
    if len(traded_by_launch) == 0:
        raise GameDataError(f"share price {symbol}: no trading day in the window on or before launch")
    a = int(traded_by_launch[-1])  # anchor: launch day, or the last trading day before it

    pct = 100.0 * (close / close[a] - 1.0)
    implied = 100.0 * (bench / bench[a] - 1.0)

    v = int((launch + pd.Timedelta(days=verdict_day) - days[0]).days)
    if v >= len(days):
        raise GameDataError(f"verdict day {verdict_day} is beyond the window end {window_to.date()}")

    market = [
        {
            "date": day.strftime("%Y-%m-%d"),
            "d": int((day - launch).days),
            "pct": round(float(pct[i]), PCT_DECIMALS) + 0.0,
            "implied_pct": round(float(implied[i]), PCT_DECIMALS) + 0.0,
            "trading": bool(trading[i]),
        }
        for i, day in enumerate(days)
    ]
    at = market[v]
    verdict = {
        "day": verdict_day,
        "pct": round(at["pct"], 2) + 0.0,
        "implied_pct": round(at["implied_pct"], 2) + 0.0,
        "gap_pct": round(at["pct"] - at["implied_pct"], 2) + 0.0,
    }
    return {"market": market, "verdict": verdict, "anchor": days[a]}
