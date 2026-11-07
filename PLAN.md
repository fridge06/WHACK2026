# Launch Day Alpha: build plan

This document is the brief for building the project. Read it fully before writing code, then work through the milestones in order. Ask before deviating from the data contract in section 4.

## 1. What we're building

A hackathon project for the Marshall Wace "New Worlds" prompt (build something that opens a door to the unexplored). Marshall Wace is a hedge fund, so the angle is finance.

**The idea:** when a big single-player game launches, it opens a new world for players. The site shows how players' interest in that world (before and after launch) lines up with the publisher's market value, and how much value the launch created or destroyed compared with the wider market.

**The product** is a static website. The full dataset holds around 25 game launches. Each time the page loads, it picks **6 at random** and lists them in a short menu. One game is shown at a time; clicking a name in the menu switches to it. There is **no automatic cycling**. Refreshing the page gives a new random set of 6.

For the game on screen, the page shows:

- the game name, publisher, stock listing and launch date
- a one-line verdict, e.g. "In its first month, CD Projekt's value fell 23.6% behind its market: down 30.1%, while its market fell 6.5%."
- a dual-axis chart over time, from **3 months before launch to 6 months after**:
  - **x-axis:** time, with month ticks and a marked launch-day line
  - **left y-axis:** a popularity index (launch month = 100), as a line with a point per month and a light filled area
  - **right y-axis:** the % change in the company's market value since launch, as a bold daily line
  - a dashed line showing what the company would have been worth had it moved with its market index
  - shading between those two lines after launch: the value the launch created or lost

Popularity is **monthly**, because most of the sources we can get update monthly. Share prices are available daily, so market value stays daily. The chart overlays the two on the same time axis.

Market value is shown as **% change since launch**, not in £. The number of shares barely changes over the window, so the % change in market value equals the % change in the share price: no share counts or exchange rates are needed, and games are comparable across company sizes.

## 2. What already exists

- `prototype/launch-day-alpha.html`: a single-file prototype with generated placeholder data. **Use it as the visual reference** for layout, chart styling, tooltip, draw-in animation and mobile layout. **Do not copy its colours or fonts**; section 6.1 replaces them. Its behaviour is out of date in two ways: it auto-rotates through games (remove this, including the progress bars and pause button), and it uses a daily popularity series over a 30/60-day window (replace with section 5).
- **The game list:** the data teammate is choosing the ~25 games and has likely already committed a file listing them. Look through the repo for it before starting milestone 2, tell me what you found, and build the loader around its real shape. Don't assume it matches `data-templates/games.csv`.
- `data-templates/`: draft CSV templates and a README written for the data teammate. These are **provisional and partly out of date**: the date ranges in that README use the old 45/60-day window.

## 3. Architecture

```
data/raw/            inputs from the data teammate (or the mock generator)
pipeline/            Python: load → clean → compute → validate → write JSON
site/                static website (HTML, CSS, vanilla JS), reads site/data/games.json
```

The pipeline does all computation. The website only reads `site/data/games.json` and draws it. There is no server at runtime; the site is static and can be hosted on GitHub Pages.

Proposed layout:

```
.
├── PLAN.md
├── prototype/launch-day-alpha.html
├── data/
│   ├── raw/                 # real inputs from the data teammate
│   └── mock/                # generated placeholder inputs, same format as raw
├── pipeline/
│   ├── config.toml          # signals, weights, granularity, windows, verdict day
│   ├── loaders.py           # read raw files into the normalised internal format
│   ├── popularity.py        # monthly popularity index
│   ├── market.py            # daily market value, implied value, verdict
│   ├── build.py             # entry point: python -m pipeline.build [--mock]
│   ├── validate.py          # coverage report + output checks
│   └── make_mock.py         # writes placeholder inputs to data/mock/
├── tests/                   # pytest
└── site/
    ├── index.html
    ├── styles.css
    ├── app.js
    └── data/games.json      # written by the pipeline
```

Tech constraints: Python 3.11+ with pandas (use the standard library `tomllib` for config). The frontend is plain HTML/CSS/JS with no build step and no framework. Draw the chart as SVG by hand, as in the prototype. Local dev: `python -m http.server` inside `site/`, because `fetch` doesn't work from `file://`.

## 4. Data contract

There are two sides. **The output contract (4.2) is fixed**: the frontend depends on it. **The input side (4.1) is provisional**: the data teammate is still finding out which APIs exist and what they return, so the available signals, their granularity and even the file shapes may change.

Design for that:

- `loaders.py` is the only code that knows about raw file shapes. Everything downstream works on a normalised internal format. If the teammate's files arrive in a different shape, write or adjust a loader; don't touch the core logic.
- Signals are config-driven. Nothing outside `config.toml` should name a specific signal. Adding, removing or reweighting a signal, or changing its granularity, must be a config change only.
- Every assumption about the inputs that we can't confirm yet should be a named config value with a sensible default, and listed in section 8.

### 4.1 Inputs (provisional)

**Game metadata**, one row per game (the teammate's file; the draft columns are below):

```
game_id,name,short_name,publisher,city,ticker,price_symbol,benchmark_symbol,launch_date,steam_appid,wikipedia_title
```

`price_symbol` and `benchmark_symbol` are Yahoo Finance symbols. Dates are `YYYY-MM-DD`. (`pipeline/fetch.py` writes this file from the teammate's list in `data/games.csv`.)

**Signals**, long format, one row per game per period per signal:

```
game_id,date,signal,value
```

For monthly data, `date` is the first day of the month (`2020-12-01`); the loader should also accept `YYYY-MM`. A missing row means "unknown", not zero.

The signal names are **unknown until the teammate reports back**. Load whatever names appear, use those configured in `config.toml`, and warn about any that appear in the data but not in the config. Each configured signal declares its granularity (`monthly` or `daily`) and, for daily signals, how to roll them up to months (`sum` for counts like reviews, `mean` for levels like search interest).

**Prices**, daily closes in local currency, trading days only, covering every company and benchmark symbol across each game's window:

```
symbol,date,close
```

**Internal normalised format** (what loaders return):

- `games`: a DataFrame indexed by `game_id`, with the metadata columns above.
- `signals`: a DataFrame with columns `game_id, month (Period[M]), signal (str), value (float)`. Daily signals are rolled up to months inside the loader layer, per config.
- `prices`: a DataFrame with columns `symbol, date (datetime64), close (float)`.

### 4.2 Output: `site/data/games.json` (fixed)

```json
{
  "meta": {
    "generated_at": "2026-11-07T12:00:00Z",
    "placeholder": true,
    "months_before": 3,
    "months_after": 6,
    "games_per_view": 6,
    "verdict_day": 30,
    "verdict_phrase": "In its first month",
    "popularity_label": "Popularity (launch month = 100)",
    "signals": [
      { "id": "example_signal", "label": "Readable name", "weight": 0.5 }
    ]
  },
  "games": [
    {
      "id": "elden_ring",
      "name": "Elden Ring",
      "short": null,
      "publisher": "Bandai Namco",
      "city": "Tokyo",
      "ticker": "7832",
      "launch": "2022-02-25",
      "window": { "from": "2021-11-25", "to": "2022-08-25" },
      "signals_used": ["example_signal"],
      "verdict": { "day": 30, "pct": 12.4, "implied_pct": 4.5, "gap_pct": 7.9 },
      "popularity": [
        { "month": "2021-11", "m": -3, "mid": "2021-11-15", "value": 18.4 }
      ],
      "market": [
        { "date": "2021-11-25", "d": -92, "pct": -3.1, "implied_pct": 0.8, "trading": true }
      ]
    }
  ]
}
```

Field rules:

- Only games that pass validation appear in `games`. Excluded games are listed in the build report with the reason.
- `window.from` is the launch date minus 3 calendar months; `window.to` is the launch date plus 6 calendar months.
- `popularity` has exactly one entry per calendar month from the 3 months before the launch month to the 6 months after it (10 entries). `m` is months relative to the launch month (launch month is `m = 0`). `mid` is the 15th of that month, used to place the point on the time axis. `value` is a number or `null`.
- `market` has exactly one entry per calendar day across the window, in order. `d` is days from launch. `pct` is the % change in the company's market value since the anchor day; `implied_pct` is the % change it would have had moving with its market index. Both are 0 at the anchor day by construction. `trading` is false where the price was carried forward.
- `verdict.pct` and `verdict.implied_pct` are the `market` values on day `verdict.day`; `gap_pct = pct − implied_pct` (percentage points of launch-day value).
- `meta.placeholder` is true whenever any input came from the mock generator. The site must then show a "Placeholder data" badge.

## 5. Calculations

All tunable values live in `config.toml`.

### 5.1 Popularity index (monthly)

For each game and each configured signal:

1. Roll daily signals up to calendar months per config (`sum` or `mean`). Monthly signals pass through.
2. Take the 10 months from `m = -3` to `m = +6`. Don't interpolate across missing months; leave them missing.
3. Find the base value: the signal's value in the launch month (`m = 0`). If that's missing or zero, drop the signal for that game and log a warning.
4. Index the signal: `index_s(m) = 100 × value_s(m) / base_s`.

Then combine: `popularity(m)` is the weighted mean of the indexed signals available that month, with weights from config rescaled to sum to 1 over the signals present. If no signal is present, it's `null`.

Because every signal equals 100 in the launch month, signals that only exist from launch onwards (such as anything Steam-based) join without a jump.

Known caveat to mention in the README: the launch month's value mixes days before and after launch, so the 100 point is "the launch month", not "launch day". This is fine for a monthly view.

### 5.2 Market value (daily, % change since launch)

For each game, using the closes as published (Yahoo's are adjusted for splits, which keeps % changes correct):

1. Build a calendar-day series across the window. Carry the last trading day's close forward over non-trading days, and set `trading = false` on those days. If the window starts on a non-trading day, use the last close before it.
2. Find the anchor: the close on launch day, or the last trading day before it if launch fell on a non-trading day.
3. Company: `pct(t) = 100 × (close(t) / close(anchor) − 1)`. With a constant share count this is the % change in market value.
4. Market: `implied_pct(t) = 100 × (bench(t) / bench(anchor) − 1)`, with the benchmark carried forward the same way.

### 5.3 Verdict

At `verdict_day` (default 30, configurable): `gap_pct = pct(d) − implied_pct(d)`, also writing `pct(d)` and `implied_pct(d)` to the verdict.

Also write `verdict_phrase` to `meta` ("In its first week" for 7, "In its first month" for 30, otherwise "In its first N days"). The frontend phrases it: negative gaps "[publisher]'s value fell X% behind its market", positive gaps "[publisher]'s value pulled X% ahead of its market", followed by the two underlying moves.

## 6. Frontend requirements

Port the prototype into `site/index.html`, `site/styles.css` and `site/app.js`, keeping its layout but restyled per 6.1. Then:

### 6.1 Visual style (replaces the prototype's palette)

- Backgrounds: plain white (`#FFFFFF`) in light mode, neutral dark grey (`#1C1C1E`) in dark mode. No tinted (purple/lavender) backgrounds or greys; text, gridlines and axes use neutral greys.
- No decorative gradients: remove the gradient strip at the top and the gradient tab bars. The chart sits on the page background (a thin neutral border at most), not on a tinted card.
- Font: Roboto (Google Fonts) throughout, with a system sans-serif fallback.
- Series colours: **blue for popularity** (line, point markers, light blue fill), **red for market value** (bold line). The implied "moved with its market" line is a neutral grey dashed line. The shaded gap uses a light tint of the market-value red. Pick exact shades per theme so both lines stay clearly readable on white and on dark grey.
- Theme: a toggle button in the header switches light/dark. On first visit it follows `prefers-color-scheme`; the user's choice is remembered in `localStorage` (inside `try/catch`) and applied via a `data-theme` attribute on `<html>` before first paint to avoid a flash.
- Single page only; no info page.

**Game selection and menu**

- Load `data/games.json` with `fetch`, adding a cache-busting query string. Remove the in-page placeholder generator.
- On each page load, choose `meta.games_per_view` games uniformly at random from `games` (Fisher–Yates shuffle). If fewer games are available, show all of them.
- Best effort, avoid showing exactly the same set as the previous visit: remember the last set in `localStorage` inside `try/catch`, and reshuffle once if it matches. The page must work normally if storage is unavailable.
- For demos, support an optional URL parameter `?games=id1,id2,...` that overrides the random pick, so the presenter can control which games appear.
- Show the selected games as a short menu (the tab row from the prototype, without progress bars). The first game in the set shows on load. Clicking a name switches to that game; arrow keys move between names. No timers, no auto-advance, no pause button.

**Chart**

- Time axis spans from the earlier of `window.from` and the first popularity `mid`, to the later of `window.to` and the last popularity `mid`, so every monthly point is on the chart (a launch on the 5th puts the last month's mid-point after `window.to`). The market lines still cover only the window. Put ticks at the start of each month, labelled with the short month name (adding the year at January or at the first tick). Keep the vertical launch-day line labelled "Launch".
- Popularity: plot each month's point at its `mid` date, joined by a line with visible point markers and a light filled area beneath. Show `null` months as gaps, never as zero. Left-axis title from `meta.popularity_label`.
- Market value: the daily `pct` line, the dashed `implied_pct` line, and the shaded gap from launch onwards, as in the prototype. The right axis is labelled in % change since launch, with the 0% line emphasised.
- Tooltip: hovering shows the date, that day's % change in market value and in the "moved with its market" line (noting "Market closed: last close shown" when `trading` is false), and the popularity value for that calendar month.
- Keep the draw-in animation when switching games (disabled under `prefers-reduced-motion`), light and dark themes via CSS variables (see 6.1), and responsiveness down to about 360px wide.

**Other**

- If loading fails, show a clear message in the page saying the data file couldn't be loaded and how to fix it locally (serve the folder with `python -m http.server`).
- Show the "Placeholder data" badge only when `meta.placeholder` is true.
- Honesty rule: the site must not claim or imply the data is live.

## 7. Milestones

Work through these in order. Each ends with something runnable.

1. **Scaffold.** Create the layout in section 3, `requirements.txt` (pandas, pytest), `.gitignore`, and a short README with run commands.
   *Done when:* `pytest` runs and `python -m http.server` serves `site/`.

2. **Find the teammate's game list, then build the mock generator.** First locate the game list in the repo and report its location and columns. Then `make_mock.py` writes inputs to `data/mock/` in the section 4.1 format for **all games in that list** (or 25 invented ones if no list is found). Generate monthly signals with plausible shapes (a hype build-up before launch, a peak around launch, then decay), daily prices with drift and noise and no weekend rows, and a few deliberate gaps and one or two games with broken data, to exercise validation. Seed it so output is reproducible.
   *Done when:* running it produces valid inputs for every game.

3. **Pipeline core.** Loaders, popularity (5.1), market value (5.2) and verdict (5.3), plus `build.py --mock` writing `site/data/games.json` with `placeholder: true`. Include unit tests for daily-to-monthly rollup, indexing, weight rescaling with missing signals, missing base month, carry-forward, anchor selection on a weekend launch, calendar-month window edges (for example launches on the 29th–31st), and the verdict maths.
   *Done when:* `python -m pipeline.build --mock` writes a JSON file that passes milestone 4's checks, and the tests pass.

4. **Validation.** `validate.py` checks the output against 4.2: field presence and types, exactly 10 popularity months per game, one market entry per day across the window, `pct == implied_pct == 0` at the anchor, verdict consistency. It also prints a coverage report per game: signals found, months present, whether a base month was found, and why any game was excluded. Run it automatically at the end of every build. Fail loudly on contract violations; warn and exclude on per-game data problems.
   *Done when:* the deliberately broken mock games are excluded with clear reasons, and the rest build cleanly.

5. **Frontend port.** Do section 6.
   *Done when:* served locally, each refresh shows a random set of 6, the menu switches games, `?games=` works, the chart draws monthly popularity against daily market value, it works in light and dark mode and on a narrow screen, and the console is clean.

6. **Real data hookup.** Triggered when the teammate's files arrive. Run `python -m pipeline.build` (no `--mock`) against `data/raw/`. Adapt the loaders if the file shapes differ, and update `config.toml` with the real signal list, granularities and weights. Review the coverage report with the team before trusting the charts.

7. **Deploy.** Add a GitHub Actions workflow that publishes `site/` to GitHub Pages.

### Stretch goals (only after milestone 5 works)

- **Replay mode:** a button that replays a launch over time with a moving cursor, a running counter of value gained or lost, and the lines revealing progressively.
- **Hype vs Reality page:** one scatter plot across all games, showing pre-launch hype against post-launch reception, with bubble size as value created or lost.

## 8. Open questions (pending the data teammate)

Don't block on these. Pick the default, make it configurable, and keep the list current in the README.

| Question | Default for now |
|---|---|
| Where the game list lives and its columns | Find it in the repo (milestone 2); fall back to the draft columns in 4.1 |
| Which signals exist, and their names | Unknown; config-driven, mock uses invented names |
| Granularity of each signal | Monthly; daily signals rolled up per config |
| Signal weights | Equal weights across configured signals |
| Benchmark index per exchange | Read from game metadata; exclude the game with a clear reason if missing |
| Share counts and FX rates | Not needed: market value is shown as % change since launch |
| Verdict horizon | 30 days |
| Whether raw data is committed to git | Teammate's choice; mock data committed |
| Number of games shown per load | 6, via `games_per_view` in config |

## 9. Don't

- Don't hard-code signal names, game names or the number of games outside config and data.
- Don't add automatic cycling, timers or a pause button.
- Don't add a frontend framework, bundler or charting library without asking.
- Don't interpolate missing months or write zeros for missing data anywhere in the pipeline.
- Don't change the output contract in 4.2 without updating this plan and the frontend together.
- Don't present placeholder numbers as real anywhere on the site.
