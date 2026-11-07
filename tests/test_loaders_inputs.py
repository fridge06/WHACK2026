import logging

import pandas as pd
import pytest

from pipeline.loaders import load_games, load_prices, load_signals

CFG = {
    "reviews": {"granularity": "daily", "rollup": "sum", "weight": 1},
    "viewers": {"granularity": "daily", "rollup": "mean", "weight": 1},
    "search": {"granularity": "monthly", "weight": 1},
}


def csv(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def as_dict(df):
    return {(r.game_id, str(r.month), r.signal): r.value for r in df.itertuples()}


def test_daily_sum_and_mean_rollup(tmp_path):
    path = csv(tmp_path, "signals.csv", "game_id,date,signal,value\n"
               "g,2020-12-30,reviews,10\n"
               "g,2020-12-31,reviews,5\n"
               "g,2021-01-01,reviews,7\n"
               "g,2020-12-30,viewers,100\n"
               "g,2020-12-31,viewers,300\n")
    out = as_dict(load_signals(path, CFG))
    assert out[("g", "2020-12", "reviews")] == 15
    assert out[("g", "2021-01", "reviews")] == 7
    assert out[("g", "2020-12", "viewers")] == 200


def test_monthly_accepts_both_date_formats(tmp_path):
    path = csv(tmp_path, "signals.csv", "game_id,date,signal,value\n"
               "g,2020-11-01,search,40\n"
               "g,2020-12,search,90\n")
    out = as_dict(load_signals(path, CFG))
    assert out == {("g", "2020-11", "search"): 40, ("g", "2020-12", "search"): 90}
    assert load_signals(path, CFG)["month"].dtype == "period[M]"


def test_blank_values_are_unknown_not_zero(tmp_path):
    path = csv(tmp_path, "signals.csv", "game_id,date,signal,value\n"
               "g,2020-11,search,\n"
               "g,2020-12,search,90\n")
    out = as_dict(load_signals(path, CFG))
    assert ("g", "2020-11", "search") not in out


def test_unknown_signals_and_games_are_warned_and_dropped(tmp_path, caplog):
    path = csv(tmp_path, "signals.csv", "game_id,date,signal,value\n"
               "g,2020-12,search,90\n"
               "g,2020-12,mystery,1\n"
               "other,2020-12,search,5\n")
    with caplog.at_level(logging.WARNING, logger="pipeline"):
        out = load_signals(path, CFG, game_ids={"g"})
    assert set(out["signal"]) == {"search"} and set(out["game_id"]) == {"g"}
    assert "mystery" in caplog.text and "other" in caplog.text


def test_bad_signal_date_is_reported(tmp_path):
    path = csv(tmp_path, "signals.csv", "game_id,date,signal,value\ng,Dec 2020,search,1\n")
    with pytest.raises(ValueError, match="Dec 2020"):
        load_signals(path, CFG)


def test_prices_drop_bad_rows_and_sort(tmp_path):
    path = csv(tmp_path, "prices.csv", "symbol,date,close\n"
               "A,2020-01-03,11\n"
               "A,2020-01-02,10\n"
               "A,2020-01-06,\n"
               "A,2020-01-07,0\n")
    out = load_prices(path)
    assert list(out["close"]) == [10, 11]
    assert out["date"].dtype.kind == "M"


def test_games_fill_missing_columns_and_parse_numbers(tmp_path):
    path = csv(tmp_path, "games.csv", "game_name,publisher_name,release_date,shares_outstanding\n"
               "Game,Pub,2020-01-01,\"1,000\"\n"
               "Other,Pub,2020-01-01,\n")
    games = load_games(path)
    assert games.loc["game", "shares_outstanding"] == 1000
    assert pd.isna(games.loc["other", "shares_outstanding"])
    assert games.loc["game", "price_symbol"] == ""
