"""pipeline.fetch without the network: parsing, split handling, and a cache-only run."""

import copy
import json

import pandas as pd
import pytest

from pipeline import build, fetch
from pipeline.config import load_config
from pipeline.loaders import load_game_list, load_games, load_prices, load_signals
from pipeline.validate import validate_output

# --- Yahoo ------------------------------------------------------------------

def chart_payload(stamps, closes, offset=32400, currency="JPY", exchange="Tokyo"):
    return {"chart": {"result": [{
        "meta": {"currency": currency, "fullExchangeName": exchange, "gmtoffset": offset, "longName": "Co"},
        "timestamp": stamps,
        "indicators": {"quote": [{"close": closes}]},
    }], "error": None}}


def test_parse_chart_local_dates_and_bad_closes():
    # 00:00 UTC is 09:00 in Tokyo: same calendar day after the offset.
    stamps = [1679616000, 1679875200, 1679961600]  # 2023-03-24, 03-27, 03-28 at 00:00 UTC
    out = fetch.parse_chart(chart_payload(stamps, [3500.0, None, 3600.5]), "9697.T")
    assert out["closes"] == [["2023-03-24", 3500.0], ["2023-03-28", 3600.5]]
    assert out["currency"] == "JPY" and out["exchange"] == "Tokyo"


def test_parse_chart_us_offset_keeps_trading_day():
    # 13:30 UTC open on 2013-09-17 is 09:30 New York (UTC-4): still the 17th.
    out = fetch.parse_chart(chart_payload([1379424600], [17.5], offset=-14400, currency="USD", exchange="NasdaqGS"), "TTWO")
    assert out["closes"] == [["2013-09-17", 17.5]]


def test_parse_chart_no_data_is_an_error():
    with pytest.raises(fetch.FetchError, match="delisted"):
        fetch.parse_chart({"chart": {"result": None, "error": {"description": "symbol may be delisted"}}}, "ATVI")


@pytest.mark.parametrize("symbol, shown", [("CDR.WA", "CDR"), ("EMBRAC-B.ST", "EMBRAC-B"), ("TTWO", "TTWO"), ("9697.T", "9697")])
def test_display_ticker(symbol, shown):
    assert fetch.display_ticker(symbol) == shown


def test_exchange_city():
    assert fetch.exchange_city("NasdaqGS") == "New York"
    assert fetch.exchange_city("Warsaw") == "Warsaw"
    assert fetch.exchange_city("Somewhere Else") == "Somewhere Else"


# --- Steam / Wikipedia --------------------------------------------------------

def test_steam_histogram_monthly_and_weekly():
    monthly = {"success": 1, "results": {"rollup_type": "month", "rollups": [
        {"date": 1606780800, "recommendations_up": 10, "recommendations_down": 5},   # 2020-12-01
        {"date": 1609459200, "recommendations_up": 3, "recommendations_down": 1},    # 2021-01-01
    ]}}
    assert fetch.parse_steam_histogram(monthly) == [["2020-12-01", 15], ["2021-01-01", 4]]
    weekly = {"success": 1, "results": {"rollup_type": "week", "rollups": [
        {"date": 1607212800, "recommendations_up": 1, "recommendations_down": 0},    # 2020-12-06
        {"date": 1607817600, "recommendations_up": 2, "recommendations_down": 1},    # 2020-12-13
    ]}}
    assert fetch.parse_steam_histogram(weekly) == [["2020-12-01", 4]]
    assert fetch.parse_steam_histogram({"success": 2}) == []


def wiki_query(title, description="2020 video game", disambig=False, missing=False):
    page = {"title": title, "description": description}
    if disambig:
        page["pageprops"] = {"disambiguation": ""}
    if missing:
        page["missing"] = ""
    return {"query": {"pages": {"1": page}}}


def test_wiki_title_follows_redirect_result():
    assert fetch.resolve_wiki_title(wiki_query("The Witcher 3: Wild Hunt"), "The Witcher 3", False) == "The Witcher 3: Wild Hunt"


def test_wiki_disambiguation_is_rejected():
    with pytest.raises(fetch.FetchError, match="disambiguation"):
        fetch.resolve_wiki_title(wiki_query("God of War", "Topics referred to by the same term", disambig=True), "God of War", False)


def test_wiki_guessed_title_must_be_a_game():
    with pytest.raises(fetch.FetchError, match="doesn't look like a game"):
        fetch.resolve_wiki_title(wiki_query("Rust", "Iron oxide"), "Rust", False)
    # An explicit wikipedia_title is trusted.
    assert fetch.resolve_wiki_title(wiki_query("Rust (video game)", "Survival game"), "Rust (video game)", True) == "Rust (video game)"


def test_wiki_missing_page():
    with pytest.raises(fetch.FetchError, match="no Wikipedia article"):
        fetch.resolve_wiki_title(wiki_query("Nope", missing=True), "Nope", False)


def test_parse_pageviews():
    payload = {"items": [{"timestamp": "2020090100", "views": 354867}, {"timestamp": "2020100100", "views": 690037}]}
    assert fetch.parse_pageviews(payload) == [["2020-09-01", 354867], ["2020-10-01", 690037]]


# --- loader aliases for the teammate's columns ----------------------------------

def test_teammate_columns_map_to_internal_names(tmp_path):
    path = tmp_path / "games.csv"
    path.write_text("game_name,publisher_name,alpha_release_date,ticker,index,steam_appid\n"
                    "Cyberpunk 2077,CD PROJEKT RED,2020-12-10,CDR.WA,^STOXX,1091500\n", encoding="utf-8")
    g = load_game_list(path).loc["cyberpunk_2077"]
    assert g["price_symbol"] == "CDR.WA" and g["benchmark_symbol"] == "^STOXX" and g["steam_appid"] == "1091500"


# --- full run from a pre-filled cache (no network) -------------------------------

def seed_cache(cache: fetch.Cache):
    days = pd.bdate_range("2020-07-01", "2021-07-31")
    co = [[d.strftime("%Y-%m-%d"), 300.0 if d <= pd.Timestamp("2020-12-10") else 200.0] for d in days]
    ix = [[d.strftime("%Y-%m-%d"), 400.0] for d in days]
    base = {"start": "2020-07-01", "end": "2021-07-31", "exchange": "Warsaw", "name": "Co"}
    cache.write("prices", "CDR.WA", {**base, "symbol": "CDR.WA", "currency": "PLN", "closes": co})
    cache.write("prices", "^STOXX", {**base, "symbol": "^STOXX", "currency": "EUR", "closes": ix})
    weeks = pd.date_range("2020-08-30", "2021-06-27", freq="W-SUN")
    cache.write("trends", "cyberpunk_2077", {"points": [[w.strftime("%Y-%m-%d"), 50 if w.month == 12 else 10] for w in weeks]})
    cache.write("steam", "1091500", {"months": [["2020-12-01", 1000], ["2021-01-01", 500]]})
    cache.write("wikipedia", "cyberpunk_2077", {"title": "Cyberpunk 2077",
                                                "points": [[f"{p}-01", 100] for p in pd.period_range("2020-09", "2021-06", freq="M").astype(str)]})


def test_cache_only_run_produces_buildable_inputs(tmp_path):
    cfg = copy.deepcopy(load_config())
    cfg["fetch"]["cache_dir"] = str(tmp_path / "cache")
    seed_cache(fetch.Cache(tmp_path / "cache"))
    game_list = tmp_path / "list.csv"
    game_list.write_text(
        "game_name,publisher_name,alpha_release_date,ticker,index,steam_appid\n"
        "Cyberpunk 2077,CD PROJEKT RED,2020-12-10,CDR.WA,^STOXX,1091500\n"
        "Rust,Facepunch Studios,2013-12-11,,,\n", encoding="utf-8")
    out = tmp_path / "raw"

    report = fetch.run(cfg, game_list, out, sources=set())  # nothing fetched: cache only

    games = load_games(out / "games.csv")
    cp = games.loc["cyberpunk_2077"]
    assert cp["city"] == "Warsaw" and cp["ticker"] == "CDR" and cp["price_symbol"] == "CDR.WA"
    assert any("no ticker" in n for n in report["rust"]["notes"])
    assert any("PLN" in n and "EUR" in n for n in report["cyberpunk_2077"]["notes"])  # currency mismatch noted
    signals = load_signals(out / "signals.csv", cfg["signals"])
    assert set(signals["signal"]) == {"google_trends", "steam_reviews", "wikipedia_views"}
    assert set(load_prices(out / "prices.csv")["symbol"]) == {"CDR.WA", "^STOXX"}

    cfg["paths"]["raw_dir"] = str(out)
    doc, rep = build.build(cfg, mock=False)
    assert validate_output(doc) == []
    assert rep["included"] == ["cyberpunk_2077"] and "rust" in rep["excluded"]
    g = doc["games"][0]
    assert g["verdict"]["gap_pct"] == pytest.approx(-33.33, abs=0.01)  # 300 -> 200 with a flat index
    assert g["city"] == "Warsaw" and g["ticker"] == "CDR"


def test_real_build_without_fetched_files_points_to_fetch(tmp_path):
    cfg = copy.deepcopy(load_config())
    cfg["paths"]["raw_dir"] = str(tmp_path)
    with pytest.raises(FileNotFoundError, match="pipeline.fetch"):
        build.build(cfg, mock=False)
