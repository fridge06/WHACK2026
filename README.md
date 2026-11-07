# WHACK2026: Launch Day Alpha

A tool that displays the divergences between consumer popularity and publisher market valuation, measured using historical gaming and financial data.

See [PLAN.md](PLAN.md) for the full brief.

## Layout

```
data/raw/      inputs from the data teammate
data/mock/     generated placeholder inputs, same format as raw
pipeline/      Python: load -> compute -> validate -> write site/data/games.json
site/          static website (HTML, CSS, vanilla JS)
tests/         pytest
prototype/     original single-file prototype (layout reference only)
```

## Setup

Requires Python 3.11+.

```
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
```

## Run

```
pytest                          # run the tests
python -m pipeline.make_mock    # regenerate placeholder inputs in data/mock/ from data/games.csv
python -m pipeline.build --mock # build site/data/games.json from mock data (milestone 3)
python -m pipeline.fetch        # fetch real data into data/raw/ (see "Fetching real data")
python -m pipeline.build        # build from real data in data/raw/
python -m pipeline.validate     # re-check an existing site/data/games.json against the contract
```

Every build prints a coverage report (months of data per signal per game, missing launch-month bases, exclusions with reasons) and validates its output before writing. If the output breaks the contract in PLAN.md 4.2, the build fails and writes nothing.

Mock data is invented: symbols like `MOCK_P01` are fake, games from the same publisher share one fake company, and a few games are broken on purpose to exercise validation (listed in `data/mock/expected_issues.json`). The mock signals are defined under `[mock.signals]` in `pipeline/config.toml`; the real ones go under `[signals]`.

## Fetching real data

`python -m pipeline.fetch` reads the game list in `data/games.csv` and writes `games.csv`, `signals.csv` and `prices.csv` to `data/raw/`. Every source is free and needs no API key. Responses are cached in `data/raw/cache/`, so a rerun only fetches what is missing.

| Source | What it gives | Signal / use |
|---|---|---|
| Google Trends (via `pytrends`) | Weekly search interest, any date since 2004 | `google_trends` |
| Steam review histogram | Reviews per month, from the game's Steam release | `steam_reviews` |
| Wikipedia pageviews | Monthly article views, **from July 2015 only** | `wikipedia_views` |
| Yahoo Finance chart endpoint | Daily closes (split-adjusted) and the exchange | prices, city shown on the site |

Market value is shown as % change since launch, which equals the % change in the share price, so no share counts or exchange rates are needed.

Columns in `data/games.csv`, one row per game (only name, publisher and release date are required; release dates can be `YYYY-MM-DD` or `DD/MM/YYYY`):

| Column (accepted names) | What it is | Example |
|---|---|---|
| `ticker` / `company_stock_ticker` | Yahoo Finance symbol of the company that owned the game **at launch** (often the parent, not the studio). Blank if it wasn't listed. | `CDR.WA`, `TTWO`, `9697.T` |
| `index` / `yahoo_index` | Yahoo symbol of that company's market index | `^GSPC` or `^IXIC` (US), `^N225` (Tokyo), `^FCHI` (Paris), `^GDAXI` (Frankfurt), `^OMX` (Stockholm), `^STOXX` (Warsaw: Yahoo has no WIG20 prices) |
| `steam_appid` / `steam_id` | Number in the Steam store URL. A later PC port is fine; it just won't count for launch. | `1091500` |
| `wikipedia_title` | Optional. The article title, when the game name is ambiguous | `God of War (2018 video game)` |
| `trends_term` | Optional. The Google Trends search term, when the name is ambiguous | `Rust game` |

Useful options: `--only prices,trends` (some sources), `--games cyberpunk_2077,elden_ring` (some games), `--refresh` (ignore the cache). Google Trends limits how fast you can ask, so the script waits 20 seconds between searches and backs off when told to slow down (`[fetch]` in `pipeline/config.toml`). It ends with a table of what it found per game and notes on anything missing.

## Input files

| File | Mock build (`--mock`) | Real build |
|---|---|---|
| Game metadata | `data/mock/games.csv` | `data/raw/games.csv` (written by `pipeline.fetch`) |
| Signals (`game_id,date,signal,value`) | `data/mock/signals.csv` | `data/raw/signals.csv` |
| Prices (`symbol,date,close`) | `data/mock/prices.csv` | `data/raw/prices.csv` |

The build prints which games were excluded and why.

## Caveats and open questions

- **Launch month = 100, not launch day.** Popularity is monthly, so the launch month's value mixes days before and after launch.
- **Partial months.** A daily signal that only exists from launch day (e.g. reviews) covers part of the launch month, so the next month can index above 100.
- **Stale prices.** If two consecutive closes inside a game's window are more than `max_price_gap_days` (default 10) calendar days apart, or prices stop before the window ends, the game is excluded rather than showing a carried-forward price.
- **% change, not £.** Market value is the % change since launch day, which equals the change in the share price as long as the number of shares stays the same (it barely moves over a few months). Yahoo's prices are adjusted for stock splits, so splits don't distort it.
- **Currency of the index.** If the index is quoted in a different currency from the share price (e.g. `CDR.WA` in PLN against `^STOXX` in EUR), currency moves show up in the comparison. The fetch report flags these.
- **Uneven signal coverage.** Steam only covers games that were on Steam at launch, and Wikipedia pageviews start in July 2015. Games without them use the signals they have (weights rescale).
- **Companies that no longer trade** (e.g. Activision) have no prices on Yahoo, so those games are excluded.

Open questions (defaults are configurable in `pipeline/config.toml`):

| Question | Default for now |
|---|---|
| Which signals to use | Google Trends (weekly), Steam reviews and Wikipedia pageviews (monthly) |
| Signal weights | Equal |
| Google Trends region | Worldwide (`trends_geo = ""`) |
| Ticker and index per game | From `data/games.csv`; game excluded with a reason if missing |
| Verdict horizon | 30 days |
| Longest acceptable gap between closes | 10 calendar days |
| Number of games shown per load | 6 |

Serve the site locally (opening `index.html` directly won't work, because `fetch` is blocked on `file://`):

```
cd site
python -m http.server 8000
```

Then open http://localhost:8000.
