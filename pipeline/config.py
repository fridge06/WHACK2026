"""Read and check pipeline/config.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(__file__).resolve().parent / "config.toml"

GRANULARITIES = {"monthly", "daily"}
ROLLUPS = {"sum", "mean"}


def load_config(path: Path = CONFIG_PATH) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def signal_config(cfg: dict, mock: bool) -> dict:
    """The signal definitions to use: [mock.signals] for mock builds, [signals] otherwise."""
    signals = cfg["mock"]["signals"] if mock else cfg.get("signals", {})
    check_signals(signals)
    return signals


def check_signals(signals: dict) -> None:
    """Raise ValueError if the signal config is unusable."""
    if not signals:
        raise ValueError("no popularity signals configured; add at least one under [signals] in pipeline/config.toml")
    for name, s in signals.items():
        where = f"signal {name!r} in pipeline/config.toml"
        if s.get("granularity") not in GRANULARITIES:
            raise ValueError(f"{where}: granularity must be one of {sorted(GRANULARITIES)}")
        if s["granularity"] == "daily" and s.get("rollup") not in ROLLUPS:
            raise ValueError(f"{where}: daily signals need rollup = one of {sorted(ROLLUPS)}")
        weight = s.get("weight", 1.0)
        if not isinstance(weight, (int, float)) or weight <= 0:
            raise ValueError(f"{where}: weight must be a positive number")
