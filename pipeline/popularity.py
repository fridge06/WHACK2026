"""Monthly popularity index (PLAN.md 5.1).

Each configured signal is indexed to its launch-month value (= 100), then the
indexed signals are combined month by month as a weighted mean over the signals
present that month. Missing months stay missing; nothing is interpolated.
"""

from __future__ import annotations

import math

import pandas as pd

from pipeline.errors import GameDataError


def popularity_months(launch: pd.Timestamp, months_before: int, months_after: int) -> list[pd.Period]:
    launch_month = pd.Timestamp(launch).to_period("M")
    return [launch_month + k for k in range(-months_before, months_after + 1)]


def compute_popularity(
    game_signals: pd.DataFrame,
    launch: pd.Timestamp,
    months_before: int,
    months_after: int,
    signal_cfg: dict,
) -> tuple[list[dict], list[str], list[str]]:
    """Popularity entries for one game.

    game_signals: rows of the normalised signals frame for this game
    (columns month, signal, value). Returns (entries, signals_used, warnings).
    Raises GameDataError if no signal has a usable launch-month base.
    """
    months = popularity_months(launch, months_before, months_after)
    launch_month = months[months_before]
    warnings: list[str] = []
    indexed: dict[str, pd.Series] = {}

    for name in signal_cfg:
        series = game_signals.loc[game_signals["signal"] == name].set_index("month")["value"]
        if series.empty:
            warnings.append(f"signal {name}: no data")
            continue
        base = series.get(launch_month)
        if base is None or not math.isfinite(base) or base <= 0:
            warnings.append(f"signal {name}: no usable launch-month value ({launch_month}); dropped")
            continue
        indexed[name] = series.reindex(months) * 100.0 / base

    if not indexed:
        raise GameDataError(f"no popularity signal has a usable launch-month value ({launch_month})")

    entries = []
    for k, month in enumerate(months):
        present = {n: s[month] for n, s in indexed.items() if pd.notna(s[month])}
        if present:
            weights = {n: float(signal_cfg[n].get("weight", 1.0)) for n in present}
            value = sum(weights[n] * v for n, v in present.items()) / sum(weights.values())
            value = round(float(value), 2)
        else:
            value = None
        entries.append({
            "month": str(month),
            "m": k - months_before,
            "mid": f"{month}-15",
            "value": value,
        })
    return entries, list(indexed), warnings
