"""Output checks against the contract in PLAN.md 4.2, plus the coverage report.

Run automatically at the end of every build (the build fails and writes nothing if
the output breaks the contract). Can also check an existing file:

    python -m pipeline.validate [site/data/games.json]
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import pandas as pd

from pipeline.dates import window_bounds
from pipeline.popularity import popularity_months

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
PCT_TOLERANCE = 0.011      # verdict values are rounded to 2 dp


class ContractError(Exception):
    """The output breaks the PLAN.md 4.2 contract. This is a pipeline bug, not a data problem."""


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_str(v) -> bool:
    return isinstance(v, str) and v != ""


def _is_opt_str(v) -> bool:
    return v is None or _is_str(v)


def _check_fields(obj, spec: dict, where: str, errors: list[str]) -> bool:
    if not isinstance(obj, dict):
        errors.append(f"{where}: expected an object")
        return False
    ok = True
    for key, (check, desc) in spec.items():
        if key not in obj:
            errors.append(f"{where}: missing {key!r}")
            ok = False
        elif not check(obj[key]):
            errors.append(f"{where}.{key}: expected {desc}, got {obj[key]!r}")
            ok = False
    return ok


META_SPEC = {
    "generated_at": (lambda v: isinstance(v, str) and bool(TIMESTAMP_RE.match(v)), "UTC timestamp YYYY-MM-DDTHH:MM:SSZ"),
    "placeholder": (lambda v: isinstance(v, bool), "boolean"),
    "months_before": (lambda v: _is_int(v) and v >= 0, "non-negative integer"),
    "months_after": (lambda v: _is_int(v) and v >= 0, "non-negative integer"),
    "games_per_view": (lambda v: _is_int(v) and v > 0, "positive integer"),
    "verdict_day": (lambda v: _is_int(v) and v > 0, "positive integer"),
    "verdict_phrase": (_is_str, "string"),
    "popularity_label": (_is_str, "string"),
    "signals": (lambda v: isinstance(v, list) and len(v) > 0, "non-empty list"),
}
SIGNAL_SPEC = {
    "id": (_is_str, "string"),
    "label": (_is_str, "string"),
    "weight": (lambda v: _is_num(v) and v > 0, "positive number"),
}
GAME_SPEC = {
    "id": (_is_str, "string"),
    "name": (_is_str, "string"),
    "short": (_is_opt_str, "string or null"),
    "publisher": (_is_str, "string"),
    "city": (_is_opt_str, "string or null"),
    "ticker": (_is_opt_str, "string or null"),
    "launch": (lambda v: isinstance(v, str) and bool(DATE_RE.match(v)), "date YYYY-MM-DD"),
    "window": (lambda v: isinstance(v, dict), "object"),
    "signals_used": (lambda v: isinstance(v, list) and len(v) > 0 and all(_is_str(s) for s in v), "non-empty list of strings"),
    "verdict": (lambda v: isinstance(v, dict), "object"),
    "popularity": (lambda v: isinstance(v, list), "list"),
    "market": (lambda v: isinstance(v, list) and len(v) > 0, "non-empty list"),
}
_is_pct = (lambda v: _is_num(v) and v > -100, "number above -100")
VERDICT_SPEC = {
    "day": (_is_int, "integer"),
    "pct": _is_pct,
    "implied_pct": _is_pct,
    "gap_pct": (_is_num, "number"),
}
POP_SPEC = {
    "month": (lambda v: isinstance(v, str) and bool(MONTH_RE.match(v)), "month YYYY-MM"),
    "m": (_is_int, "integer"),
    "mid": (lambda v: isinstance(v, str) and bool(DATE_RE.match(v)), "date YYYY-MM-DD"),
    "value": (lambda v: v is None or _is_num(v), "number or null"),
}
MARKET_SPEC = {
    "date": (lambda v: isinstance(v, str) and bool(DATE_RE.match(v)), "date YYYY-MM-DD"),
    "d": (_is_int, "integer"),
    "pct": _is_pct,
    "implied_pct": _is_pct,
    "trading": (lambda v: isinstance(v, bool), "boolean"),
}


def _check_game(g: dict, meta: dict, signal_ids: set[str], errors: list[str]) -> None:
    where = f"game {g.get('id', '?')}"
    if not _check_fields(g, GAME_SPEC, where, errors):
        return

    unknown = set(g["signals_used"]) - signal_ids
    if unknown:
        errors.append(f"{where}.signals_used: not in meta.signals: {sorted(unknown)}")

    launch = pd.Timestamp(g["launch"])
    before, after = meta["months_before"], meta["months_after"]
    w_from, w_to = window_bounds(launch, before, after)
    expected_window = {"from": w_from.strftime("%Y-%m-%d"), "to": w_to.strftime("%Y-%m-%d")}
    if g["window"] != expected_window:
        errors.append(f"{where}.window: expected {expected_window}, got {g['window']}")

    # popularity: one entry per calendar month, m = -before..after
    months = popularity_months(launch, before, after)
    pop = g["popularity"]
    if len(pop) != len(months):
        errors.append(f"{where}.popularity: expected {len(months)} months, got {len(pop)}")
    else:
        for i, (entry, month) in enumerate(zip(pop, months)):
            pw = f"{where}.popularity[{i}]"
            if not _check_fields(entry, POP_SPEC, pw, errors):
                continue
            expected = {"month": str(month), "m": i - before, "mid": f"{month}-15"}
            for key, val in expected.items():
                if entry[key] != val:
                    errors.append(f"{pw}.{key}: expected {val!r}, got {entry[key]!r}")
        launch_entry = pop[before] if len(pop) > before else {}
        if isinstance(launch_entry, dict) and launch_entry.get("value") != 100:
            errors.append(f"{where}.popularity: launch month value must be 100, got {launch_entry.get('value')!r}")

    # market: one entry per calendar day across the window, in order
    market = g["market"]
    days = pd.date_range(w_from, w_to, freq="D")
    if len(market) != len(days):
        errors.append(f"{where}.market: expected {len(days)} days ({expected_window['from']} to {expected_window['to']}), got {len(market)}")
        return
    for i, (entry, day) in enumerate(zip(market, days)):
        mw = f"{where}.market[{i}]"
        if not _check_fields(entry, MARKET_SPEC, mw, errors):
            return
        if entry["date"] != day.strftime("%Y-%m-%d") or entry["d"] != (day - launch).days:
            errors.append(f"{mw}: expected date {day.date()} d={(day - launch).days}, got {entry['date']} d={entry['d']}")
            return

    anchors = [m for m in market if m["d"] <= 0 and m["trading"]]
    if not anchors:
        errors.append(f"{where}.market: no trading day on or before launch (no anchor)")
        return
    anchor = anchors[-1]
    if anchor["pct"] != 0 or anchor["implied_pct"] != 0:
        errors.append(f"{where}.market: pct and implied_pct must be 0 at the anchor {anchor['date']}, "
                      f"got {anchor['pct']} and {anchor['implied_pct']}")

    # verdict
    v = g["verdict"]
    if not _check_fields(v, VERDICT_SPEC, f"{where}.verdict", errors):
        return
    if v["day"] != meta["verdict_day"]:
        errors.append(f"{where}.verdict.day: expected {meta['verdict_day']}, got {v['day']}")
    at = next((m for m in market if m["d"] == v["day"]), None)
    if at is None:
        errors.append(f"{where}.verdict: day {v['day']} is outside the market series")
        return
    for key in ("pct", "implied_pct"):
        if abs(at[key] - v[key]) > PCT_TOLERANCE:
            errors.append(f"{where}.verdict.{key}: {v[key]} but the market value on day {v['day']} is {at[key]}")
    gap = at["pct"] - at["implied_pct"]
    if abs(gap - v["gap_pct"]) > PCT_TOLERANCE:
        errors.append(f"{where}.verdict.gap_pct: {v['gap_pct']} but pct - implied_pct on day {v['day']} is {gap:.2f}")


def validate_output(doc) -> list[str]:
    """Every way `doc` breaks the PLAN.md 4.2 contract. Empty list means valid."""
    errors: list[str] = []
    try:
        json.dumps(doc, allow_nan=False)
    except (TypeError, ValueError) as err:
        return [f"output is not valid JSON: {err}"]
    if not isinstance(doc, dict) or set(doc) != {"meta", "games"}:
        return ["top level must be an object with exactly 'meta' and 'games'"]

    meta = doc["meta"]
    if not _check_fields(meta, META_SPEC, "meta", errors):
        return errors
    for i, s in enumerate(meta["signals"]):
        _check_fields(s, SIGNAL_SPEC, f"meta.signals[{i}]", errors)
    signal_ids = {s.get("id") for s in meta["signals"] if isinstance(s, dict)}

    games = doc["games"]
    if not isinstance(games, list) or not games:
        errors.append("games: expected a non-empty list")
        return errors
    ids = [g.get("id") for g in games if isinstance(g, dict)]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        errors.append(f"games: duplicate ids {dupes}")
    for g in games:
        _check_game(g, meta, signal_ids, errors)
    return errors


def check_output(doc) -> None:
    errors = validate_output(doc)
    if errors:
        shown = "\n  ".join(errors[:30])
        more = f"\n  ... and {len(errors) - 30} more" if len(errors) > 30 else ""
        raise ContractError(f"output breaks the PLAN.md 4.2 contract ({len(errors)} problem(s)):\n  {shown}{more}")


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------

def coverage(games: pd.DataFrame, signals: pd.DataFrame, signal_cfg: dict,
             months_before: int, months_after: int, excluded: dict[str, str]) -> list[dict]:
    """Per game: for each configured signal, months with data in the window and whether
    the launch-month base exists; plus whether the game was included, and why not."""
    by_game = {gid: grp for gid, grp in signals.groupby("game_id")}
    empty = signals.iloc[0:0]
    rows = []
    for gid, game in games.iterrows():
        months = popularity_months(game["launch_date"], months_before, months_after)
        launch_month = months[months_before]
        mine = by_game.get(gid, empty)
        cells = {}
        for name in signal_cfg:
            s = mine[(mine["signal"] == name) & mine["month"].isin(months)]
            base = s.loc[s["month"] == launch_month, "value"]
            cells[name] = {"months": int(s["month"].nunique()), "base": bool((base > 0).any())}
        rows.append({"game_id": gid, "included": gid not in excluded, "reason": excluded.get(gid), "signals": cells})
    return rows


def format_coverage(rows: list[dict], n_months: int) -> str:
    if not rows:
        return "Coverage: no games."
    names = list(rows[0]["signals"])
    id_w = max(len("game"), *(len(r["game_id"]) for r in rows))
    col_w = [max(len(n), len(f"{n_months}/{n_months} no base")) for n in names]
    header = f"{'game':<{id_w}}  {'status':<8}  " + "  ".join(f"{n:<{w}}" for n, w in zip(names, col_w))
    lines = [f"Coverage (months with data out of {n_months}; 'no base' = no launch-month value)", header, "-" * len(header)]
    for r in rows:
        cells = []
        for n, w in zip(names, col_w):
            c = r["signals"][n]
            text = "-" if c["months"] == 0 else f"{c['months']}/{n_months}" + ("" if c["base"] else " no base")
            cells.append(f"{text:<{w}}")
        status = "ok" if r["included"] else "EXCLUDED"
        lines.append(f"{r['game_id']:<{id_w}}  {status:<8}  " + "  ".join(cells))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from pipeline.config import ROOT, load_config

    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0]) if args else ROOT / load_config()["paths"]["output"]
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        print(f"Could not read {path}: {err}", file=sys.stderr)
        return 1
    errors = validate_output(doc)
    if errors:
        print(f"{path}: {len(errors)} contract problem(s)", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1
    print(f"{path}: valid ({len(doc['games'])} games)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
