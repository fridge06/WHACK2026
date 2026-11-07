import json

import numpy as np
import pandas as pd
import pytest

from pipeline import make_mock
from pipeline.config import ROOT, load_config
from pipeline.dates import window_bounds
from pipeline.loaders import GAME_COLUMNS, load_game_list

SEED = 7


@pytest.fixture(scope="module")
def cfg():
    return load_config()


@pytest.fixture(scope="module")
def games():
    return make_mock.invented_game_list(np.random.default_rng(SEED), n=12)


@pytest.fixture(scope="module")
def result(games, cfg):
    return make_mock.generate(games, cfg, SEED)


def test_reproducible(games, cfg, result):
    again = make_mock.generate(games, cfg, SEED)
    for key in ("games", "signals", "prices"):
        pd.testing.assert_frame_equal(result[key], again[key])
    assert result["issues"] == again["issues"]


def test_different_seed_differs(games, cfg, result):
    other = make_mock.generate(games, cfg, SEED + 1)
    assert not result["prices"]["close"].equals(other["prices"]["close"])


def test_game_metadata_shape(games, result):
    out = result["games"]
    assert list(out.columns) == GAME_COLUMNS
    assert list(out["game_id"]) == list(games.index)
    assert out["price_symbol"].str.startswith("MOCK_").all()
    # games with the same publisher share one invented company
    assert (out.groupby("publisher")["price_symbol"].nunique() == 1).all()


def test_prices_weekdays_only_and_positive(result):
    p = result["prices"]
    dates = pd.to_datetime(p["date"])
    assert (dates.dt.day_of_week < 5).all()
    assert (p["close"] > 0).all()
    assert not p.duplicated(["symbol", "date"]).any()


def test_prices_cover_every_window_except_delisted(result, cfg):
    p = result["prices"].assign(date=lambda d: pd.to_datetime(d["date"]))
    delisted = {gid for gid, why in result["issues"]["excluded"].items() if "delisted" in why}
    assert len(delisted) == 1
    for row in result["games"].itertuples():
        start, end = window_bounds(pd.Timestamp(row.launch_date), cfg["window"]["months_before"], cfg["window"]["months_after"])
        for sym in (row.price_symbol, row.benchmark_symbol):
            dates = p.loc[p["symbol"] == sym, "date"]
            assert dates.min() <= start, (row.game_id, sym)
            if sym == row.price_symbol and row.game_id in delisted:
                assert dates.max() < end
            else:
                assert dates.max() >= end, (row.game_id, sym)


def test_signals_present_without_zeros_for_gaps(result, cfg):
    s = result["signals"]
    assert set(s["signal"]) == set(cfg["mock"]["signals"])
    assert s["value"].notna().all()
    assert not s.duplicated(["game_id", "signal", "date"]).any()


def test_no_base_game_has_no_launch_month_rows(result):
    no_base = [g for g, why in result["issues"]["excluded"].items() if "base month" in why]
    assert len(no_base) == 1
    gid = no_base[0]
    launch = pd.Timestamp(result["games"].set_index("game_id").at[gid, "launch_date"])
    s = result["signals"]
    months = s.loc[s["game_id"] == gid, "date"].str[:7]
    assert launch.strftime("%Y-%m") not in set(months)
    assert len(months) > 0


def test_gaps_are_absent_rows(result, cfg):
    s = result["signals"]
    for gid, notes in result["issues"]["gaps"].items():
        for note in notes:
            if "missing entirely" in note:
                name = note.split()[1]
                assert not ((s["game_id"] == gid) & (s["signal"] == name)).any()


def test_month_formats_follow_config(result, cfg):
    s = result["signals"]
    for name, sig in cfg["mock"]["signals"].items():
        dates = s.loc[s["signal"] == name, "date"]
        if sig["granularity"] == "daily":
            assert dates.str.fullmatch(r"\d{4}-\d{2}-\d{2}").all()
        elif sig.get("month_format") == "year_month":
            assert dates.str.fullmatch(r"\d{4}-\d{2}").all()
        else:
            assert dates.str.fullmatch(r"\d{4}-\d{2}-01").all()


def test_starts_at_launch_signals_have_nothing_before_launch(result, cfg):
    s = result["signals"]
    launches = result["games"].set_index("game_id")["launch_date"]
    for name, sig in cfg["mock"]["signals"].items():
        if sig.get("starts_at_launch"):
            rows = s[s["signal"] == name]
            assert (rows["date"] >= rows["game_id"].map(launches)).all()


def test_main_writes_every_game_in_the_real_list(tmp_path, cfg):
    list_path = ROOT / cfg["paths"]["game_list"]
    if not list_path.exists():
        pytest.skip("no game list in the repo")
    assert make_mock.main(["--out", str(tmp_path)]) == 0
    written = pd.read_csv(tmp_path / "games.csv")
    assert list(written["game_id"]) == list(load_game_list(list_path).index)
    issues = json.loads((tmp_path / "expected_issues.json").read_text())
    assert issues["placeholder"] is True
    for name in ("signals.csv", "prices.csv"):
        assert (tmp_path / name).stat().st_size > 0
