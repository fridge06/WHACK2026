import pandas as pd
import pytest

from pipeline.dates import window_bounds
from pipeline.loaders import load_game_list, slugify


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Assassin's Creed Shadows", "assassins_creed_shadows"),
        ("The Witcher 3: Wild Hunt", "the_witcher_3_wild_hunt"),
        ("ELDEN RING", "elden_ring"),
        ("Marvel’s Spider-Man 2", "marvels_spider_man_2"),
        ("Pokémon Légendes", "pokemon_legendes"),
    ],
)
def test_slugify(name, expected):
    assert slugify(name) == expected


def write(tmp_path, text, bom=True):
    path = tmp_path / "games.csv"
    path.write_bytes(("﻿" if bom else "").encode("utf-8") + text.encode("utf-8"))
    return path


def test_teammate_columns_with_bom(tmp_path):
    path = write(tmp_path, "game_name,publisher_name,release_date\nCyberpunk 2077,CD PROJEKT RED,2020-12-10\n")
    games = load_game_list(path)
    assert list(games.index) == ["cyberpunk_2077"]
    row = games.loc["cyberpunk_2077"]
    assert row["name"] == "Cyberpunk 2077"
    assert row["publisher"] == "CD PROJEKT RED"
    assert row["launch_date"] == pd.Timestamp("2020-12-10")


def test_plan_columns_and_explicit_ids(tmp_path):
    path = write(
        tmp_path,
        "game_id,name,publisher,launch_date,ticker\ncp,Cyberpunk 2077,CD Projekt,2020-12-10,CDR\n",
        bom=False,
    )
    games = load_game_list(path)
    assert list(games.index) == ["cp"]
    assert games.loc["cp", "ticker"] == "CDR"


def test_duplicate_names_get_unique_ids(tmp_path):
    path = write(tmp_path, "game_name,publisher_name,release_date\nGame,A,2020-01-01\nGame,B,2021-01-01\n")
    assert list(load_game_list(path).index) == ["game", "game_2"]


def test_blank_rows_are_ignored(tmp_path):
    path = write(tmp_path, "game_name,publisher_name,release_date\nGame,A,2020-01-01\n,,\n")
    assert len(load_game_list(path)) == 1


def test_bad_date_is_reported(tmp_path):
    path = write(tmp_path, "game_name,publisher_name,release_date\nGame,A,10/12/2020\n")
    with pytest.raises(ValueError, match="Game"):
        load_game_list(path)


def test_missing_column_is_reported(tmp_path):
    path = write(tmp_path, "game_name,release_date\nGame,2020-01-01\n")
    with pytest.raises(ValueError, match="publisher"):
        load_game_list(path)


@pytest.mark.parametrize(
    "launch, start, end",
    [
        ("2024-02-29", "2023-11-29", "2024-08-29"),  # leap day
        ("2023-05-31", "2023-02-28", "2023-11-30"),  # 31st clamps to month end
        ("2020-12-10", "2020-09-10", "2021-06-10"),  # crosses a year
    ],
)
def test_window_bounds_calendar_months(launch, start, end):
    assert window_bounds(pd.Timestamp(launch), 3, 6) == (pd.Timestamp(start), pd.Timestamp(end))
