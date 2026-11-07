"""Read raw input files into the normalised internal format (PLAN.md 4.1).

This is the only module that knows about raw file shapes. If the data teammate's
files change shape, adjust this module (and the aliases below), nothing downstream.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

import pandas as pd

log = logging.getLogger("pipeline")

# Game metadata columns in the internal format (PLAN.md 4.1), in file order.
GAME_COLUMNS = [
    "game_id", "name", "short_name", "publisher", "city", "ticker",
    "price_symbol", "benchmark_symbol", "launch_date", "steam_appid",
    "wikipedia_title", "shares_outstanding", "gbp_per_local",
]
REQUIRED_GAME_LIST_COLUMNS = ["name", "publisher", "launch_date"]

# Column names seen in the teammate's files -> internal names.
GAME_COLUMN_ALIASES = {
    "game_name": "name",
    "publisher_name": "publisher",
    "release_date": "launch_date",
    "alpha_release_date": "launch_date",
}


def slugify(text: str) -> str:
    """'Assassin's Creed Shadows' -> 'assassins_creed_shadows'."""
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
    text = re.sub(r"['’]", "", text.lower())
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def load_game_list(path: Path) -> pd.DataFrame:
    """Read a game list, indexed by game_id.

    Accepts the teammate's column names (see GAME_COLUMN_ALIASES) or the PLAN.md 4.1
    names, with or without a byte-order mark. Needs at least name, publisher and
    launch date; any other 4.1 columns present are kept as text. Missing game_ids are
    derived from the name.
    """
    df = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    df = df.rename(columns=GAME_COLUMN_ALIASES)
    missing = [c for c in REQUIRED_GAME_LIST_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: game list is missing column(s) {missing}; found {list(df.columns)}")

    df = df.apply(lambda col: col.str.strip())
    df = df[(df != "").any(axis=1)].copy()

    dates = pd.to_datetime(df["launch_date"], format="%Y-%m-%d", errors="coerce")
    bad = df.loc[dates.isna(), ["name", "launch_date"]]
    if not bad.empty:
        rows = ", ".join(f"{n!r} ({d!r})" for n, d in bad.itertuples(index=False))
        raise ValueError(f"{path}: launch dates must be YYYY-MM-DD; bad rows: {rows}")
    df["launch_date"] = dates

    ids = df["game_id"] if "game_id" in df.columns else pd.Series("", index=df.index)
    ids = ids.where(ids != "", df["name"].map(slugify))
    seen: dict[str, int] = {}
    unique = []
    for gid in ids:
        seen[gid] = seen.get(gid, 0) + 1
        if seen[gid] > 1:
            log.warning("duplicate game_id %r; renaming to %s_%d", gid, gid, seen[gid])
            gid = f"{gid}_{seen[gid]}"
        unique.append(gid)
    df["game_id"] = unique
    return df.set_index("game_id")


# ---------------------------------------------------------------------------
# Full inputs (PLAN.md 4.1) -> internal format
# ---------------------------------------------------------------------------

NUMERIC_GAME_COLUMNS = ["shares_outstanding", "gbp_per_local"]


def load_games(path: Path) -> pd.DataFrame:
    """Game metadata indexed by game_id, with every PLAN.md 4.1 column present.

    Missing text columns become "", missing or unparseable numbers become NaN
    (the game is then excluded downstream with a reason, not here).
    """
    games = load_game_list(path)
    for col in GAME_COLUMNS[1:]:
        if col not in games.columns:
            games[col] = ""
    for col in NUMERIC_GAME_COLUMNS:
        games[col] = pd.to_numeric(games[col].astype(str).str.replace(",", "", regex=False), errors="coerce")
    return games[GAME_COLUMNS[1:]]


def _parse_signal_dates(dates: pd.Series, path: Path) -> pd.Series:
    """Accept YYYY-MM-DD or YYYY-MM (the latter means the first of the month)."""
    text = dates.astype(str).str.strip()
    full = pd.to_datetime(text, format="%Y-%m-%d", errors="coerce")
    month = pd.to_datetime(text, format="%Y-%m", errors="coerce")
    parsed = full.fillna(month)
    bad = text[parsed.isna()]
    if not bad.empty:
        raise ValueError(f"{path}: signal dates must be YYYY-MM-DD or YYYY-MM; e.g. {bad.unique()[:5].tolist()}")
    return parsed


def load_signals(path: Path, signal_cfg: dict, game_ids=None) -> pd.DataFrame:
    """Long-format signals -> columns game_id, month (Period[M]), signal, value.

    Only configured signals are kept (others are warned about). Daily signals are
    rolled up to calendar months per their configured rollup; monthly signals pass
    through. Blank or non-numeric values are unknown and dropped, never zero.
    """
    raw = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    raw.columns = [c.strip() for c in raw.columns]
    missing = [c for c in ("game_id", "date", "signal", "value") if c not in raw.columns]
    if missing:
        raise ValueError(f"{path}: signals file is missing column(s) {missing}; found {list(raw.columns)}")

    df = pd.DataFrame({
        "game_id": raw["game_id"].str.strip(),
        "signal": raw["signal"].str.strip(),
        "date": _parse_signal_dates(raw["date"], path) if len(raw) else pd.Series(dtype="datetime64[ns]"),
        "value": pd.to_numeric(raw["value"].str.strip(), errors="coerce"),
    })
    df = df[df["value"].notna()]

    unknown = sorted(set(df["signal"]) - set(signal_cfg))
    if unknown:
        log.warning("signals in %s but not in config (ignored): %s", path.name, ", ".join(unknown))
    if game_ids is not None:
        stray = sorted(set(df["game_id"]) - set(game_ids))
        if stray:
            log.warning("signals for game_ids not in the game list (ignored): %s", ", ".join(stray))
        df = df[df["game_id"].isin(game_ids)]

    df = df.assign(month=df["date"].dt.to_period("M"))
    parts = []
    for name, s in signal_cfg.items():
        part = df[df["signal"] == name]
        if part.empty:
            log.warning("configured signal %r has no data in %s", name, path.name)
            continue
        keys = ["game_id", "month"]
        if s["granularity"] == "daily":
            dupes = part.duplicated(["game_id", "date"])
            if dupes.any():
                log.warning("signal %r: %d duplicate daily rows; keeping the last", name, int(dupes.sum()))
                part = part.drop_duplicates(["game_id", "date"], keep="last")
            rolled = part.groupby(keys)["value"].agg(s["rollup"])
        else:
            dupes = part.duplicated(keys)
            if dupes.any():
                log.warning("signal %r: %d duplicate monthly rows; using their mean", name, int(dupes.sum()))
            rolled = part.groupby(keys)["value"].mean()
        parts.append(rolled.reset_index().assign(signal=name))

    if not parts:
        return pd.DataFrame({"game_id": pd.Series(dtype=str), "month": pd.Series(dtype="period[M]"),
                             "signal": pd.Series(dtype=str), "value": pd.Series(dtype=float)})
    return pd.concat(parts, ignore_index=True)[["game_id", "month", "signal", "value"]]


def load_prices(path: Path) -> pd.DataFrame:
    """Daily closes -> columns symbol, date (datetime64), close (float), sorted.

    Rows with a missing or non-positive close are dropped with a warning.
    """
    raw = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
    raw.columns = [c.strip() for c in raw.columns]
    missing = [c for c in ("symbol", "date", "close") if c not in raw.columns]
    if missing:
        raise ValueError(f"{path}: prices file is missing column(s) {missing}; found {list(raw.columns)}")
    df = pd.DataFrame({
        "symbol": raw["symbol"].str.strip(),
        "date": pd.to_datetime(raw["date"].str.strip(), format="%Y-%m-%d", errors="coerce"),
        "close": pd.to_numeric(raw["close"].str.strip(), errors="coerce"),
    })
    bad_date = df["date"].isna()
    if bad_date.any():
        raise ValueError(f"{path}: price dates must be YYYY-MM-DD; e.g. {raw.loc[bad_date, 'date'].unique()[:5].tolist()}")
    bad = df["close"].isna() | (df["close"] <= 0)
    if bad.any():
        log.warning("%s: dropping %d rows with a missing or non-positive close", path.name, int(bad.sum()))
        df = df[~bad]
    dupes = df.duplicated(["symbol", "date"])
    if dupes.any():
        log.warning("%s: %d duplicate symbol/date rows; keeping the last", path.name, int(dupes.sum()))
        df = df.drop_duplicates(["symbol", "date"], keep="last")
    return df.sort_values(["symbol", "date"]).reset_index(drop=True)
