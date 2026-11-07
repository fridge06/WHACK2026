import pandas as pd
import pytest

from pipeline.errors import GameDataError
from pipeline.popularity import compute_popularity, popularity_months

LAUNCH = pd.Timestamp("2020-12-10")
CFG = {"a": {"granularity": "monthly", "weight": 3}, "b": {"granularity": "monthly", "weight": 1}}


def frame(rows):
    return pd.DataFrame(
        [{"month": pd.Period(m, "M"), "signal": s, "value": v} for m, s, v in rows],
        columns=["month", "signal", "value"],
    )


def by_month(entries):
    return {e["month"]: e["value"] for e in entries}


def test_ten_months_with_offsets_and_mid_dates():
    entries, _, _ = compute_popularity(frame([("2020-12", "a", 5)]), LAUNCH, 3, 6, CFG)
    assert [e["month"] for e in entries] == [str(pd.Period("2020-09", "M") + k) for k in range(10)]
    assert [e["m"] for e in entries] == list(range(-3, 7))
    assert entries[0]["mid"] == "2020-09-15"


def test_indexing_to_launch_month():
    entries, used, _ = compute_popularity(frame([("2020-11", "a", 20), ("2020-12", "a", 40), ("2021-01", "a", 30)]), LAUNCH, 3, 6, {"a": CFG["a"]})
    v = by_month(entries)
    assert v["2020-12"] == 100
    assert v["2020-11"] == 50
    assert v["2021-01"] == 75
    assert used == ["a"]


def test_missing_months_stay_null_never_zero_or_interpolated():
    entries, _, _ = compute_popularity(frame([("2020-12", "a", 40), ("2021-02", "a", 20)]), LAUNCH, 3, 6, {"a": CFG["a"]})
    v = by_month(entries)
    assert v["2021-01"] is None
    assert v["2020-09"] is None
    assert v["2021-02"] == 50


def test_weights_rescale_over_signals_present_each_month():
    rows = [
        ("2020-12", "a", 10), ("2020-12", "b", 50),   # both 100
        ("2021-01", "a", 20), ("2021-01", "b", 25),   # a=200, b=50 -> (3*200 + 1*50)/4
        ("2021-02", "b", 100),                        # only b=200 -> 200
    ]
    v = by_month(compute_popularity(frame(rows), LAUNCH, 3, 6, CFG)[0])
    assert v["2020-12"] == 100
    assert v["2021-01"] == pytest.approx(162.5)
    assert v["2021-02"] == 200


def test_signal_missing_base_month_is_dropped_with_warning():
    rows = [("2020-12", "a", 10), ("2021-01", "a", 20), ("2021-01", "b", 999)]
    entries, used, warnings = compute_popularity(frame(rows), LAUNCH, 3, 6, CFG)
    assert used == ["a"]
    assert by_month(entries)["2021-01"] == 200
    assert any("b" in w and "launch-month" in w for w in warnings)


def test_zero_base_is_unusable():
    rows = [("2020-12", "a", 0), ("2020-12", "b", 10)]
    _, used, _ = compute_popularity(frame(rows), LAUNCH, 3, 6, CFG)
    assert used == ["b"]


def test_no_usable_signal_excludes_the_game():
    with pytest.raises(GameDataError, match="launch-month"):
        compute_popularity(frame([("2021-01", "a", 20)]), LAUNCH, 3, 6, CFG)


@pytest.mark.parametrize("launch, first, last", [
    ("2023-08-31", "2023-05", "2024-02"),
    ("2024-02-29", "2023-11", "2024-08"),
    ("2023-01-30", "2022-10", "2023-07"),
])
def test_month_range_for_end_of_month_launches(launch, first, last):
    months = popularity_months(pd.Timestamp(launch), 3, 6)
    assert len(months) == 10
    assert (str(months[0]), str(months[-1])) == (first, last)
