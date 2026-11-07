"""Pipeline entry point: python -m pipeline.build [--mock] [--out PATH]

Loads inputs, computes popularity (PLAN.md 5.1), market value (5.2) and verdicts
(5.3), and writes site/data/games.json in the format of PLAN.md 4.2. Games with
data problems are excluded and listed in the build report with the reason.

  --mock   read placeholder inputs from data/mock/ (meta.placeholder = true)
  default  read the game list from data/games.csv and signals/prices from data/raw/
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from pipeline.config import ROOT, load_config, signal_config
from pipeline.dates import window_bounds
from pipeline.errors import GameDataError
from pipeline.loaders import load_games, load_prices, load_signals
from pipeline.market import compute_market, verdict_phrase
from pipeline.popularity import compute_popularity
from pipeline.validate import ContractError, check_output, coverage, format_coverage

log = logging.getLogger("pipeline")


def input_paths(cfg: dict, mock: bool) -> dict[str, Path]:
    paths = cfg["paths"]
    if mock:
        base = ROOT / paths["mock_dir"]
        return {"games": base / "games.csv", "signals": base / "signals.csv", "prices": base / "prices.csv"}
    base = ROOT / paths["raw_dir"]
    return {"games": ROOT / paths["game_list"], "signals": base / "signals.csv", "prices": base / "prices.csv"}


def _text_or_none(value) -> str | None:
    text = "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value).strip()
    return text or None


def build(cfg: dict, mock: bool) -> tuple[dict, dict]:
    """Returns (output document, report). The report has included, excluded, warnings."""
    signal_cfg = signal_config(cfg, mock)
    paths = input_paths(cfg, mock)
    for kind, path in paths.items():
        if not path.exists():
            raise FileNotFoundError(f"{kind} input not found: {path}")

    games = load_games(paths["games"])
    signals = load_signals(paths["signals"], signal_cfg, game_ids=set(games.index))
    prices = load_prices(paths["prices"])
    closes = {sym: grp.set_index("date")["close"] for sym, grp in prices.groupby("symbol")}

    before, after = cfg["window"]["months_before"], cfg["window"]["months_after"]
    verdict_day = cfg["verdict"]["day"]
    max_gap = cfg["market"]["max_price_gap_days"]
    signals_by_game = {gid: grp for gid, grp in signals.groupby("game_id")}
    empty = signals.iloc[0:0]

    out_games, excluded, warnings = [], {}, {}
    for gid, game in games.iterrows():
        launch = game["launch_date"]
        w_from, w_to = window_bounds(launch, before, after)
        try:
            popularity, used, notes = compute_popularity(signals_by_game.get(gid, empty), launch, before, after, signal_cfg)
            market = compute_market(game, closes, w_from, w_to, verdict_day, max_gap)
        except GameDataError as err:
            excluded[gid] = str(err)
            continue
        if notes:
            warnings[gid] = notes
        out_games.append({
            "id": gid,
            "name": game["name"],
            "short": _text_or_none(game["short_name"]),
            "publisher": game["publisher"],
            "city": _text_or_none(game["city"]),
            "ticker": _text_or_none(game["ticker"]),
            "launch": launch.strftime("%Y-%m-%d"),
            "window": {"from": w_from.strftime("%Y-%m-%d"), "to": w_to.strftime("%Y-%m-%d")},
            "signals_used": used,
            "verdict": market["verdict"],
            "popularity": popularity,
            "market": market["market"],
        })

    total_weight = sum(float(s.get("weight", 1.0)) for s in signal_cfg.values())
    doc = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "placeholder": bool(mock),
            "currency": cfg["site"]["currency"],
            "months_before": before,
            "months_after": after,
            "games_per_view": cfg["site"]["games_per_view"],
            "verdict_day": verdict_day,
            "verdict_phrase": verdict_phrase(verdict_day),
            "popularity_label": cfg["site"]["popularity_label"],
            "signals": [
                {"id": name, "label": s.get("label", name), "weight": round(float(s.get("weight", 1.0)) / total_weight, 4)}
                for name, s in signal_cfg.items()
            ],
        },
        "games": out_games,
    }
    report = {
        "included": [g["id"] for g in out_games],
        "excluded": excluded,
        "warnings": warnings,
        "coverage": coverage(games, signals, signal_cfg, before, after, excluded),
        "n_months": before + after + 1,
    }
    return doc, report


def print_report(report: dict, out: Path | None) -> None:
    print(format_coverage(report["coverage"], report["n_months"]))
    print()
    written = f" Wrote {out}" if out else " Nothing written."
    print(f"Included {len(report['included'])} game(s), excluded {len(report['excluded'])}.{written}")
    for gid, why in report["excluded"].items():
        print(f"  EXCLUDED {gid}: {why}")
    for gid, notes in report["warnings"].items():
        for note in notes:
            print(f"  warning  {gid}: {note}")


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser(prog="python -m pipeline.build", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mock", action="store_true", help="read placeholder inputs from data/mock/")
    parser.add_argument("--out", type=Path, default=ROOT / cfg["paths"]["output"], help="output JSON path")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    try:
        doc, report = build(cfg, args.mock)
    except (FileNotFoundError, ValueError) as err:
        print(f"Build failed: {err}", file=sys.stderr)
        return 1
    if not doc["games"]:
        print_report(report, None)
        print("Build failed: no game passed validation; nothing written.", file=sys.stderr)
        return 1
    try:
        check_output(doc)
    except ContractError as err:
        print_report(report, None)
        print(f"Build failed: {err}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print_report(report, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
