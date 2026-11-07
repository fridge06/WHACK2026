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

Serve the site locally (opening `index.html` directly won't work, because `fetch` is blocked on `file://`):

```
cd site
python -m http.server 8000
```

Then open http://localhost:8000.
