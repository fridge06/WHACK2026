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
