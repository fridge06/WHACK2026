import pandas as pd
import pytest

from pipeline.dates import window_bounds
from pipeline.errors import GameDataError
from pipeline.market import carry_forward, compute_market, verdict_phrase


def weekday_series(start, end, value=10.0, overrides=None):
    days = pd.bdate_range(start, end)
    s = pd.Series(value, index=days, dtype=float)
    for date, v in (overrides or {}).items():
        s[pd.Timestamp(date)] = v
    return s.sort_index()


def game(launch, **extra):
    base = {"launch_date": pd.Timestamp(launch), "price_symbol": "CO", "benchmark_symbol": "IDX"}
    base.update(extra)
    return pd.Series(base)


def run(launch, co, idx, day=30, gap=10):
    w_from, w_to = window_bounds(pd.Timestamp(launch), 3, 6)
    return compute_market(game(launch), {"CO": co, "IDX": idx}, w_from, w_to, day, gap)


# --- carry-forward -----------------------------------------------------------

def test_carry_forward_fills_weekends_and_flags_them():
    closes = pd.Series([1.0, 2.0], index=pd.to_datetime(["2020-01-03", "2020-01-06"]))  # Fri, Mon
    days = pd.date_range("2020-01-03", "2020-01-06")
    values, trading = carry_forward(closes, days, 10, "x")
    assert list(values) == [1, 1, 1, 2]
    assert list(trading) == [True, False, False, True]


def test_window_starting_on_a_non_trading_day_uses_last_close_before_it():
    closes = pd.Series([5.0, 6.0], index=pd.to_datetime(["2020-01-03", "2020-01-06"]))
    days = pd.date_range("2020-01-04", "2020-01-06")  # starts Saturday
    values, trading = carry_forward(closes, days, 10, "x")
    assert list(values) == [5, 5, 6]
    assert list(trading) == [False, False, True]


def test_no_close_before_window_start_is_an_error():
    closes = pd.Series([5.0], index=pd.to_datetime(["2020-01-06"]))
    with pytest.raises(GameDataError, match="on or before"):
        carry_forward(closes, pd.date_range("2020-01-04", "2020-01-06"), 10, "x")


def test_long_gap_inside_window_is_an_error():
    closes = pd.Series([5.0, 6.0], index=pd.to_datetime(["2020-01-01", "2020-01-20"]))
    with pytest.raises(GameDataError, match="19 days"):
        carry_forward(closes, pd.date_range("2020-01-01", "2020-01-20"), 10, "x")


def test_prices_ending_before_window_end_is_an_error():
    closes = pd.Series([5.0], index=pd.to_datetime(["2020-01-01"]))
    with pytest.raises(GameDataError, match="delisted"):
        carry_forward(closes, pd.date_range("2020-01-01", "2020-02-01"), 10, "x")


# --- anchor ------------------------------------------------------------------

def test_weekend_launch_anchors_on_friday():
    launch = "2021-03-06"  # Saturday
    co = weekday_series("2020-11-01", "2021-10-01", 10.0, {"2021-03-05": 12.0})
    idx = weekday_series("2020-11-01", "2021-10-01", 100.0, {"2021-03-05": 200.0})
    res = run(launch, co, idx)
    assert res["anchor"] == pd.Timestamp("2021-03-05")
    by_date = {m["date"]: m for m in res["market"]}
    fri, sat, thu = by_date["2021-03-05"], by_date["2021-03-06"], by_date["2021-03-04"]
    assert fri["pct"] == fri["implied_pct"] == 0
    assert sat["trading"] is False and sat["pct"] == 0 and sat["d"] == 0
    assert thu["pct"] == pytest.approx(100 * (10 / 12 - 1), abs=1e-4)      # relative to the Friday anchor
    assert thu["implied_pct"] == pytest.approx(-50.0)


def test_launch_on_holiday_weekday_anchors_on_previous_trading_day():
    launch = "2021-03-10"  # Wednesday with no close
    co = weekday_series("2020-11-01", "2021-10-01").drop(pd.Timestamp(launch))
    idx = weekday_series("2020-11-01", "2021-10-01", 100.0)
    assert run(launch, co, idx)["anchor"] == pd.Timestamp("2021-03-09")


# --- window, values, verdict -------------------------------------------------

@pytest.mark.parametrize("launch", ["2023-08-31", "2024-02-29", "2023-01-29", "2023-03-30"])
def test_one_market_entry_per_calendar_day(launch):
    co = weekday_series("2022-01-01", "2025-01-01")
    idx = weekday_series("2022-01-01", "2025-01-01", 100.0)
    res = run(launch, co, idx)
    w_from, w_to = window_bounds(pd.Timestamp(launch), 3, 6)
    dates = [m["date"] for m in res["market"]]
    assert dates[0] == w_from.strftime("%Y-%m-%d") and dates[-1] == w_to.strftime("%Y-%m-%d")
    assert len(dates) == (w_to - w_from).days + 1
    assert [m["d"] for m in res["market"]] == list(range(-(pd.Timestamp(launch) - w_from).days, (w_to - pd.Timestamp(launch)).days + 1))


def test_pct_change_is_independent_of_price_level():
    # Same moves at very different price levels (e.g. yen vs dollars) give the same % change.
    launch = "2021-03-10"
    idx = weekday_series("2020-11-01", "2021-10-01", 100.0)
    results = []
    for level in (0.5, 50.0, 5000.0):
        co = weekday_series("2020-11-01", "2021-10-01", level)
        co[co.index > pd.Timestamp(launch)] = level * 1.25
        results.append(run(launch, co, idx)["market"][-1]["pct"])
    assert results == [25.0, 25.0, 25.0]


def test_verdict_company_falls_with_flat_market():
    launch = "2021-03-10"
    co = weekday_series("2020-11-01", "2021-10-01", 10.0)
    co[co.index > pd.Timestamp(launch)] = 9.0
    idx = weekday_series("2020-11-01", "2021-10-01", 100.0)
    v = run(launch, co, idx)["verdict"]
    assert v == {"day": 30, "pct": -10.0, "implied_pct": 0.0, "gap_pct": -10.0}


def test_verdict_company_flat_while_market_rises():
    launch = "2021-03-10"
    co = weekday_series("2020-11-01", "2021-10-01", 10.0)
    idx = weekday_series("2020-11-01", "2021-10-01", 100.0)
    idx[idx.index > pd.Timestamp(launch)] = 110.0
    v = run(launch, co, idx)["verdict"]
    assert (v["pct"], v["implied_pct"], v["gap_pct"]) == (0.0, 10.0, -10.0)


def test_verdict_both_move():
    launch = "2021-03-10"
    co = weekday_series("2020-11-01", "2021-10-01", 10.0)
    co[co.index > pd.Timestamp(launch)] = 7.0          # -30%
    idx = weekday_series("2020-11-01", "2021-10-01", 100.0)
    idx[idx.index > pd.Timestamp(launch)] = 93.5       # -6.5%
    v = run(launch, co, idx)["verdict"]
    assert (v["pct"], v["implied_pct"], v["gap_pct"]) == (-30.0, -6.5, -23.5)


def test_verdict_on_a_weekend_uses_carried_values():
    launch = "2021-03-04"  # day 30 = Saturday 2021-04-03
    co = weekday_series("2020-11-01", "2021-10-01", 10.0, {"2021-04-02": 11.0})
    idx = weekday_series("2020-11-01", "2021-10-01", 100.0)
    v = run(launch, co, idx)["verdict"]
    assert v["gap_pct"] == pytest.approx(10.0)


def test_verdict_beyond_window_is_an_error():
    co = weekday_series("2020-11-01", "2021-10-01")
    idx = weekday_series("2020-11-01", "2021-10-01", 100.0)
    with pytest.raises(GameDataError, match="beyond"):
        run("2021-03-10", co, idx, day=400)


@pytest.mark.parametrize("field, value", [
    ("price_symbol", ""), ("benchmark_symbol", None), ("price_symbol", float("nan")),
])
def test_missing_metadata_is_an_error(field, value):
    launch = "2021-03-10"
    w_from, w_to = window_bounds(pd.Timestamp(launch), 3, 6)
    with pytest.raises(GameDataError, match=field):
        compute_market(game(launch, **{field: value}), {}, w_from, w_to, 30, 10)


def test_unknown_symbol_is_an_error():
    launch = "2021-03-10"
    w_from, w_to = window_bounds(pd.Timestamp(launch), 3, 6)
    with pytest.raises(GameDataError, match="CO"):
        compute_market(game(launch), {"IDX": weekday_series("2020-11-01", "2021-10-01")}, w_from, w_to, 30, 10)


@pytest.mark.parametrize("day, phrase", [(7, "In its first week"), (30, "In its first month"), (90, "In its first 90 days")])
def test_verdict_phrase(day, phrase):
    assert verdict_phrase(day) == phrase
