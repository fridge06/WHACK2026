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
python -m pipeline.build        # build from real data in data/raw/ (milestone 6)
```

Mock data is invented: symbols like `MOCK_P01` are fake, games from the same publisher share one fake company, and a few games are broken on purpose to exercise validation (listed in `data/mock/expected_issues.json`). The mock signals are defined under `[mock.signals]` in `pipeline/config.toml`; the real ones go under `[signals]`.

## Input files

| File | Mock build (`--mock`) | Real build |
|---|---|---|
| Game metadata | `data/mock/games.csv` | `data/games.csv` |
| Signals (`game_id,date,signal,value`) | `data/mock/signals.csv` | `data/raw/signals.csv` |
| Prices (`symbol,date,close`) | `data/mock/prices.csv` | `data/raw/prices.csv` |

The build prints which games were excluded and why. A real build needs at least one signal under `[signals]` in `pipeline/config.toml`.

## Caveats and open questions

- **Launch month = 100, not launch day.** Popularity is monthly, so the launch month's value mixes days before and after launch.
- **Partial months.** A daily signal that only exists from launch day (e.g. reviews) covers part of the launch month, so the next month can index above 100.
- **Stale prices.** If two consecutive closes inside a game's window are more than `max_price_gap_days` (default 10) calendar days apart, or prices stop before the window ends, the game is excluded rather than showing a carried-forward price.
- **Fixed exchange rate.** Each game uses one GBP rate (launch day), so currency swings don't affect the result.

Pending the data teammate (defaults are configurable in `pipeline/config.toml`):

| Question | Default for now |
|---|---|
| Which signals exist, their names and granularity | None configured; mock uses invented names |
| Signal weights | Set per signal in config |
| Benchmark index, share count and FX rate per game | Read from game metadata; game excluded with a reason if missing |
| Verdict horizon | 30 days |
| Longest acceptable gap between closes | 10 calendar days |
| Number of games shown per load | 6 |

Serve the site locally (opening `index.html` directly won't work, because `fetch` is blocked on `file://`):

```
cd site
python -m http.server 8000
```

Then open http://localhost:8000.
