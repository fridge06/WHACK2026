"""Fetch real inputs into data/raw/ in the PLAN.md 4.1 formats.

Usage:
    python -m pipeline.fetch                          # everything, reusing the cache
    python -m pipeline.fetch --only prices,trends     # some sources only
    python -m pipeline.fetch --games cyberpunk_2077   # some games only
    python -m pipeline.fetch --refresh                # ignore the cache for the chosen sources

Reads the teammate's game list (data/games.csv). Besides name, publisher and
launch date, these optional columns are used when present:
    ticker              Yahoo Finance symbol of the listed company (CDR.WA, TTWO, 9697.T)
    index               Yahoo Finance symbol of its market index (^GSPC, ^N225, ^STOXX)
    steam_appid         Steam app id (number in the store URL)
    wikipedia_title     English Wikipedia article, if the game name is ambiguous
    trends_term         Google Trends search term (defaults to the game name)
(The teammate's names company_stock_ticker, yahoo_index and steam_id also work.)

Market value is shown as % change since launch, which equals the % change in the
share price, so no share counts or exchange rates are needed.

Sources (all free, no API keys):
    prices     Yahoo Finance chart endpoint: daily closes and the exchange
    trends     Google Trends via pytrends: weekly search interest
    steam      Steam review histogram: reviews per month
    wikipedia  Wikimedia pageviews: monthly views (data exists from July 2015)

Writes data/raw/games.csv, data/raw/signals.csv and data/raw/prices.csv.
Responses are cached in data/raw/cache/ so reruns only fetch what is missing;
the output files are always rebuilt from the whole cache.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from pathlib import Path

import pandas as pd

from pipeline.config import ROOT, load_config
from pipeline.dates import window_bounds
from pipeline.loaders import GAME_COLUMNS, load_game_list

SOURCES = ["prices", "trends", "steam", "wikipedia"]

# Signal names written to signals.csv; [signals] in config.toml must use the same names.
SIGNAL_TRENDS = "google_trends"
SIGNAL_STEAM = "steam_reviews"
SIGNAL_WIKI = "wikipedia_views"

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"
STEAM_HISTOGRAM = "https://store.steampowered.com/appreviewhistogram/"
WIKI_API = "https://en.wikipedia.org/w/api.php"
PAGEVIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/"
PAGEVIEWS_START = pd.Timestamp("2015-07-01")

# Yahoo exchange names -> city shown on the site ("Listed in Tokyo as 9697").
EXCHANGE_CITY = {
    "NasdaqGS": "New York", "NasdaqGM": "New York", "NasdaqCM": "New York", "NYSE": "New York",
    "NYSEArca": "New York", "NYSE American": "New York", "NMS": "New York", "NYQ": "New York",
    "Tokyo": "Tokyo", "Osaka": "Osaka", "Paris": "Paris", "Warsaw": "Warsaw", "Stockholm": "Stockholm",
    "London": "London", "LSE": "London", "XETRA": "Frankfurt", "Frankfurt": "Frankfurt",
    "Helsinki": "Helsinki", "Copenhagen": "Copenhagen", "Oslo": "Oslo", "Amsterdam": "Amsterdam",
    "HKSE": "Hong Kong", "KSE": "Seoul", "KOSDAQ": "Seoul", "Shanghai": "Shanghai", "Shenzhen": "Shenzhen",
    "Toronto": "Toronto", "ASX": "Sydney", "Milan": "Milan", "Madrid": "Madrid", "Swiss": "Zurich",
}


class FetchError(Exception):
    pass


def say(msg: str = "") -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# HTTP and cache
# ---------------------------------------------------------------------------

class Http:
    def __init__(self, user_agent: str, retries: int = 3, timeout: int = 30):
        self.user_agent, self.retries, self.timeout = user_agent, retries, timeout

    def get_json(self, url: str, params: dict | None = None):
        if params:
            url += "?" + urllib.parse.urlencode(params)
        short = url.split("?")[0]
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as err:
                if err.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    time.sleep(5 * 2 ** attempt)
                    continue
                try:
                    payload = json.loads(err.read().decode("utf-8", "replace"))
                except ValueError:
                    payload = None
                raise FetchError(_http_message(err.code, payload, short)) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
                if attempt < self.retries:
                    time.sleep(5 * 2 ** attempt)
                    continue
                raise FetchError(f"network error for {short}: {err}") from None
            except ValueError:
                raise FetchError(f"{short} did not return JSON") from None


def _http_message(code: int, payload, url: str) -> str:
    detail = ""
    if isinstance(payload, dict):
        err = (payload.get("chart") or {}).get("error") or payload.get("error") or payload.get("detail") or payload.get("message")
        if isinstance(err, dict):
            detail = err.get("description") or err.get("message") or ""
        elif err:
            detail = str(err)
    return f"HTTP {code} from {url}" + (f": {detail}" if detail else "")


class Cache:
    def __init__(self, root: Path):
        self.root = root

    def _path(self, source: str, key: str) -> Path:
        return self.root / source / (urllib.parse.quote(str(key), safe="") + ".json")

    def read(self, source: str, key: str):
        path = self._path(source, key)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None

    def write(self, source: str, key: str, data) -> None:
        path = self._path(source, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Parsing (pure functions, tested without network)
# ---------------------------------------------------------------------------

def parse_chart(payload: dict, symbol: str) -> dict:
    """Yahoo chart JSON -> {currency, exchange, name, closes [[date, close]]}.

    Yahoo's closes are adjusted for stock splits, so % changes across a split are right."""
    chart = (payload or {}).get("chart") or {}
    results = chart.get("result")
    if not results:
        err = chart.get("error") or {}
        raise FetchError(f"Yahoo has no data for {symbol}" + (f": {err.get('description')}" if err.get("description") else ""))
    r = results[0]
    meta = r.get("meta") or {}
    offset = int(meta.get("gmtoffset") or 0)
    to_date = lambda ts: pd.Timestamp(int(ts) + offset, unit="s").strftime("%Y-%m-%d")
    stamps = r.get("timestamp") or []
    quotes = ((r.get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
    closes = [[to_date(ts), float(c)] for ts, c in zip(stamps, quotes) if c is not None and math.isfinite(c) and c > 0]
    if not closes:
        raise FetchError(f"Yahoo returned no closing prices for {symbol} in this range")
    return {
        "currency": meta.get("currency"),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "name": meta.get("longName") or meta.get("shortName"),
        "closes": closes,
    }


def display_ticker(symbol: str) -> str:
    """'CDR.WA' -> 'CDR', 'EMBRAC-B.ST' -> 'EMBRAC-B', 'TTWO' -> 'TTWO'."""
    return symbol.rsplit(".", 1)[0] if "." in symbol else symbol


def exchange_city(exchange: str | None) -> str:
    return EXCHANGE_CITY.get(exchange or "", exchange or "")


def parse_steam_histogram(payload: dict) -> list[list]:
    """Steam review histogram -> [[YYYY-MM-01, reviews that month]] (weekly rollups summed by month)."""
    results = (payload or {}).get("results") or {}
    if not (payload or {}).get("success") or not results.get("rollups"):
        return []
    months: dict[str, int] = {}
    for r in results["rollups"]:
        month = pd.Timestamp(int(r["date"]), unit="s").strftime("%Y-%m-01")
        months[month] = months.get(month, 0) + int(r.get("recommendations_up", 0)) + int(r.get("recommendations_down", 0))
    return sorted([m, v] for m, v in months.items())


def resolve_wiki_title(payload: dict, requested: str, explicit: bool) -> str:
    """Pick the article from a Wikipedia query (with redirects). Raise if it's missing,
    a disambiguation page, or (when the title was guessed) not about a video game."""
    query = (payload or {}).get("query") or {}
    pages = list((query.get("pages") or {}).values())
    if not pages or "missing" in pages[0] or "invalid" in pages[0]:
        raise FetchError(f"no Wikipedia article called {requested!r}; set wikipedia_title")
    page = pages[0]
    title = page["title"]
    if "disambiguation" in (page.get("pageprops") or {}):
        raise FetchError(f"Wikipedia {title!r} is a disambiguation page; set wikipedia_title")
    description = (page.get("description") or "").lower()
    if not explicit and "game" not in description:
        raise FetchError(f"Wikipedia {title!r} doesn't look like a game ({description or 'no description'}); set wikipedia_title")
    return title


def parse_pageviews(payload: dict) -> list[list]:
    return [
        [f"{i['timestamp'][:4]}-{i['timestamp'][4:6]}-01", int(i["views"])]
        for i in (payload or {}).get("items") or []
    ]


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

class Fetcher:
    def __init__(self, cfg: dict, cache: Cache, sources: set[str], refresh: bool):
        f = cfg["fetch"]
        self.http = Http(f["user_agent"])
        self.cache = cache
        self.sources = sources
        self.refresh = refresh
        self.trends_geo = f.get("trends_geo", "")
        self.trends_delay = float(f.get("trends_delay_seconds", 20))
        self.trends_retries = int(f.get("trends_max_retries", 4))
        self._trends = None
        self._trends_last = 0.0

    def _use_cache(self, source: str) -> bool:
        return source not in self.sources or not self.refresh

    def _may_fetch(self, source: str) -> bool:
        return source in self.sources

    # -- prices --------------------------------------------------------------
    def prices(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> dict | None:
        s, e = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
        cached = self.cache.read("prices", symbol)
        if cached and self._use_cache("prices") and cached["start"] <= s and cached["end"] >= e:
            return cached
        if not self._may_fetch("prices"):
            if cached:
                return cached
            raise FetchError(f"no cached prices for {symbol}; run with --only prices")
        say(f"  prices    {symbol} {s} to {e}")
        payload = self.http.get_json(YAHOO_CHART + urllib.parse.quote(symbol, safe=""), {
            "period1": int(start.timestamp()), "period2": int((end + pd.Timedelta(days=1)).timestamp()),
            "interval": "1d",
        })
        data = {"symbol": symbol, "start": s, "end": e, **parse_chart(payload, symbol)}
        self.cache.write("prices", symbol, data)
        return data

    # -- Google Trends ---------------------------------------------------------
    def trends(self, game_id: str, term: str, start: pd.Timestamp, end: pd.Timestamp) -> list[list]:
        want = {"term": term, "geo": self.trends_geo, "start": f"{start:%Y-%m-%d}", "end": f"{end:%Y-%m-%d}"}
        cached = self.cache.read("trends", game_id)
        if cached and self._use_cache("trends") and all(cached.get(k) == v for k, v in want.items()):
            return cached["points"]
        if not self._may_fetch("trends"):
            if cached:
                return cached["points"]
            raise FetchError("no cached Google Trends data; run with --only trends")
        say(f"  trends    {term!r} {want['start']} to {want['end']} (geo={self.trends_geo or 'worldwide'})")
        points = self._trends_request(term, f"{want['start']} {want['end']}")
        self.cache.write("trends", game_id, {**want, "points": points})
        return points

    def _trends_request(self, term: str, timeframe: str) -> list[list]:
        try:
            from pytrends.exceptions import ResponseError, TooManyRequestsError
            from pytrends.request import TrendReq
        except ImportError:
            raise FetchError("pytrends is not installed; run pip install -r requirements.txt") from None
        if self._trends is None:
            self._trends = TrendReq(hl="en-GB", tz=0, timeout=(10, 30))
        for attempt in range(self.trends_retries + 1):
            wait = self.trends_delay - (time.monotonic() - self._trends_last)
            if self._trends_last and wait > 0:
                time.sleep(wait)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    self._trends.build_payload([term], timeframe=timeframe, geo=self.trends_geo)
                    df = self._trends.interest_over_time()
                self._trends_last = time.monotonic()
                break
            except (TooManyRequestsError, ResponseError) as err:
                self._trends_last = time.monotonic()
                status = getattr(getattr(err, "response", None), "status_code", None)
                limited = isinstance(err, TooManyRequestsError) or status == 429
                if not limited or attempt == self.trends_retries:
                    raise FetchError(f"Google Trends refused the request ({status or err})") from None
                pause = 60 * 2 ** attempt
                say(f"            Google Trends says too many requests; waiting {pause}s "
                    f"(retry {attempt + 1} of {self.trends_retries})")
                time.sleep(pause)
        if df is None or df.empty or term not in df.columns:
            return []
        return [[d.strftime("%Y-%m-%d"), int(v)] for d, v in df[term].items()]

    # -- Steam -----------------------------------------------------------------
    def steam(self, appid: str) -> list[list]:
        cached = self.cache.read("steam", appid)
        if cached is not None and self._use_cache("steam"):
            return cached["months"]
        if not self._may_fetch("steam"):
            raise FetchError("no cached Steam data; run with --only steam")
        say(f"  steam     app {appid}")
        payload = self.http.get_json(f"{STEAM_HISTOGRAM}{urllib.parse.quote(appid)}", {
            "l": "english", "review_score_preference": 0, "review_type": "all", "purchase_type": "all",
        })
        months = parse_steam_histogram(payload)
        self.cache.write("steam", appid, {"appid": appid, "months": months})
        return months

    # -- Wikipedia -------------------------------------------------------------
    def wikipedia(self, game_id: str, requested: str, explicit: bool, start: pd.Timestamp, end: pd.Timestamp) -> tuple[str, list[list]]:
        start = max(start, PAGEVIEWS_START)
        if start > end:
            raise FetchError("Wikipedia page views only exist from July 2015")
        want = {"requested": requested, "start": f"{start:%Y-%m-%d}", "end": f"{end:%Y-%m-%d}"}
        cached = self.cache.read("wikipedia", game_id)
        usable = cached and (all(cached.get(k) == v for k, v in want.items()) or not self._may_fetch("wikipedia"))
        if usable and (self._use_cache("wikipedia") or not self._may_fetch("wikipedia")):
            if cached.get("error"):
                raise FetchError(cached["error"])
            return cached["title"], cached["points"]
        if not self._may_fetch("wikipedia"):
            raise FetchError("no cached Wikipedia data; run with --only wikipedia")
        payload = self.http.get_json(WIKI_API, {
            "action": "query", "format": "json", "redirects": 1, "prop": "pageprops|description",
            "ppprop": "disambiguation", "titles": requested,
        })
        try:
            title = resolve_wiki_title(payload, requested, explicit)
        except FetchError as err:  # a data problem, not a network one: remember it
            self.cache.write("wikipedia", game_id, {**want, "error": str(err)})
            raise
        say(f"  wikipedia {title!r}")
        article = urllib.parse.quote(title.replace(" ", "_"), safe="")
        try:
            views = self.http.get_json(f"{PAGEVIEWS}{article}/monthly/{start:%Y%m%d}00/{end:%Y%m%d}00")
            points = parse_pageviews(views)
        except FetchError as err:
            if "HTTP 404" not in str(err):
                raise
            points = []
        self.cache.write("wikipedia", game_id, {**want, "title": title, "points": points})
        return title, points


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def _text(row: pd.Series, col: str) -> str:
    value = row.get(col, "")
    return "" if value is None or (isinstance(value, float) and math.isnan(value)) else str(value).strip()


def run(cfg: dict, list_path: Path, out_dir: Path, sources: set[str], game_ids: list[str] | None = None,
        refresh: bool = False) -> dict:
    """Fetch what's needed and write games.csv, signals.csv, prices.csv to out_dir.
    Returns a report {game_id: {"notes": [...], "counts": {...}}}."""
    games = load_game_list(list_path)
    if game_ids:
        unknown = sorted(set(game_ids) - set(games.index))
        if unknown:
            raise ValueError(f"unknown game id(s): {', '.join(unknown)}; ids are: {', '.join(games.index)}")
        games = games.loc[game_ids]

    cache = Cache(ROOT / cfg["fetch"]["cache_dir"])
    f = Fetcher(cfg, cache, sources, refresh)
    before, after = cfg["window"]["months_before"], cfg["window"]["months_after"]
    today = pd.Timestamp.today().normalize()

    spans = {}
    for gid, g in games.iterrows():
        w_from, w_to = window_bounds(g["launch_date"], before, after)
        spans[gid] = (w_from, w_to, w_from.to_period("M").start_time, min(w_to.to_period("M").end_time.normalize(), today))

    report = {gid: {"notes": [], "counts": {}} for gid in games.index}

    # Prices: one request per symbol covering all its games' windows.
    say("Prices")
    need: dict[str, list] = {}
    for gid, g in games.iterrows():
        for col in ("price_symbol", "benchmark_symbol"):
            sym = _text(g, col)
            if sym:
                w_from, w_to = spans[gid][:2]
                need.setdefault(sym, []).append((gid, w_from - pd.Timedelta(days=31), min(w_to + pd.Timedelta(days=7), today)))
    price_data, price_errors = {}, {}
    for sym, uses in need.items():
        start, end = min(u[1] for u in uses), max(u[2] for u in uses)
        try:
            price_data[sym] = f.prices(sym, start, end)
        except FetchError as err:
            price_errors[sym] = str(err)
            for gid, *_ in uses:
                report[gid]["notes"].append(f"prices: {err}")

    rows_games, rows_signals = [], []
    say("Popularity")
    for gid, g in games.iterrows():
        notes, counts = report[gid]["notes"], report[gid]["counts"]
        launch = g["launch_date"]
        w_from, w_to, f_from, f_to = spans[gid]
        symbol, bench = _text(g, "price_symbol"), _text(g, "benchmark_symbol")
        out = {c: "" for c in GAME_COLUMNS}
        out.update(game_id=gid, name=g["name"], short_name=_text(g, "short_name"), publisher=g["publisher"],
                   launch_date=launch.strftime("%Y-%m-%d"), price_symbol=symbol, benchmark_symbol=bench,
                   steam_appid=_text(g, "steam_appid"))
        if not symbol:
            notes.append("no ticker (not a listed company, or not filled in yet)")
        if not bench:
            notes.append("no index")

        company = price_data.get(symbol)
        if company:
            out["ticker"] = display_ticker(symbol)
            out["city"] = exchange_city(company.get("exchange"))
            counts["price_days"] = sum(1 for d, _ in company["closes"] if spans[gid][0].strftime("%Y-%m-%d") <= d <= spans[gid][1].strftime("%Y-%m-%d"))
            index = price_data.get(bench)
            if index and company.get("currency") and index.get("currency") and company["currency"] != index["currency"]:
                notes.append(f"share price is in {company['currency']} but the index is in {index['currency']}; "
                             "currency moves will show up in the comparison")

        term = _text(g, "trends_term") or g["name"]
        if f_from <= today:
            try:
                points = f.trends(gid, term, f_from, f_to)
                counts["trends_weeks"] = len(points)
                rows_signals += [(gid, d, SIGNAL_TRENDS, v) for d, v in points]
                if not points:
                    notes.append(f"trends: no Google Trends data for {term!r}")
            except FetchError as err:
                notes.append(f"trends: {err}")

        appid = _text(g, "steam_appid")
        if appid:
            try:
                months = [m for m in f.steam(appid) if f"{f_from:%Y-%m-01}" <= m[0] <= f"{f_to:%Y-%m-01}"]
                counts["steam_months"] = len(months)
                rows_signals += [(gid, d, SIGNAL_STEAM, v) for d, v in months]
                if not months:
                    notes.append("steam: no reviews in the window (released on Steam later?)")
            except FetchError as err:
                notes.append(f"steam: {err}")

        explicit = bool(_text(g, "wikipedia_title"))
        requested = _text(g, "wikipedia_title") or g["name"]
        try:
            title, points = f.wikipedia(gid, requested, explicit, f_from, f_to)
            out["wikipedia_title"] = title
            counts["wiki_months"] = len(points)
            rows_signals += [(gid, d, SIGNAL_WIKI, v) for d, v in points]
        except FetchError as err:
            out["wikipedia_title"] = _text(g, "wikipedia_title")
            notes.append(f"wikipedia: {err}")

        rows_games.append(out)

    # Write outputs.
    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows_games, columns=GAME_COLUMNS).to_csv(out_dir / "games.csv", index=False)
    pd.DataFrame(rows_signals, columns=["game_id", "date", "signal", "value"]).to_csv(out_dir / "signals.csv", index=False)
    price_rows = [(sym, d, c) for sym, data in price_data.items() for d, c in data["closes"]]
    pd.DataFrame(price_rows, columns=["symbol", "date", "close"]).to_csv(out_dir / "prices.csv", index=False, float_format="%.10g")
    return report


def print_report(report: dict, out_dir: Path) -> None:
    say()
    say(f"{'game':<30} {'price days':>10} {'trends wks':>10} {'steam mths':>10} {'wiki mths':>10}")
    for gid, r in report.items():
        c = r["counts"]
        cell = lambda k: str(c[k]) if k in c else "-"
        say(f"{gid:<30} {cell('price_days'):>10} {cell('trends_weeks'):>10} {cell('steam_months'):>10} {cell('wiki_months'):>10}")
    noted = {gid: r["notes"] for gid, r in report.items() if r["notes"]}
    if noted:
        say()
        say("Notes")
        for gid, notes in noted.items():
            for n in notes:
                say(f"  {gid}: {n}")
    say()
    say(f"Wrote games.csv, signals.csv and prices.csv to {out_dir}")
    say("Next: python -m pipeline.build")


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser(prog="python -m pipeline.fetch", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", default=",".join(SOURCES), help=f"comma-separated sources to fetch: {','.join(SOURCES)}")
    parser.add_argument("--games", default="", help="comma-separated game ids (default: all)")
    parser.add_argument("--refresh", action="store_true", help="ignore the cache for the chosen sources")
    parser.add_argument("--list", type=Path, default=ROOT / cfg["paths"]["game_list"], help="game list CSV")
    parser.add_argument("--out", type=Path, default=ROOT / cfg["paths"]["raw_dir"], help="output folder")
    parser.add_argument("--cache", type=Path, default=ROOT / cfg["fetch"]["cache_dir"], help="cache folder")
    args = parser.parse_args(argv)
    cfg["fetch"]["cache_dir"] = str(args.cache)

    sources = {s.strip() for s in args.only.split(",") if s.strip()}
    unknown = sources - set(SOURCES)
    if unknown:
        print(f"Unknown source(s): {', '.join(sorted(unknown))}. Choose from {', '.join(SOURCES)}.", file=sys.stderr)
        return 2
    try:
        report = run(cfg, args.list, args.out, sources,
                     [g.strip() for g in args.games.split(",") if g.strip()] or None, args.refresh)
    except (ValueError, FileNotFoundError) as err:
        print(f"Fetch failed: {err}", file=sys.stderr)
        return 1
    print_report(report, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
