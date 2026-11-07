r"""
Build Google Trends links for every game in games.csv and open them in your browser.

For each row, two links are made: one searching the game name and one searching
its publisher, both over the window [release date - 3 months, release date + 6 months].
They're written to link.txt, one per line, alternating game, publisher, game, publisher...

Usage:
    python make_trends_links.py                  # write link.txt, then open every link
    python make_trends_links.py --no-open        # only write link.txt
    python make_trends_links.py --delay 5        # wait 5 seconds between tabs
    python make_trends_links.py --csv C:\path\to\games.csv --out C:\path\to\link.txt
"""

import argparse
import calendar
import csv
import time
import webbrowser
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlencode

DEFAULT_CSV = Path(r"C:\Users\aayan\GitProjects\WHACK2026\data\games.csv")
MONTHS_BEFORE = 3
MONTHS_AFTER = 6
REQUIRED_COLUMNS = {"game_name", "publisher_name", "alpha_release_date"}


def add_months(d: date, months: int) -> date:
    """Shift a date by whole months, clamping to the last day of shorter months."""
    year, month_index = divmod(d.year * 12 + (d.month - 1) + months, 12)
    month = month_index + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def build_url(search_term: str, start: date, end: date, geo: str = "GB") -> str:
    """Build a Google Trends explore URL (spaces are encoded as %20)."""
    params = {
        "q": search_term,
        "date": f"{start.isoformat()} {end.isoformat()}",
        "geo": geo,
    }
    return "https://trends.google.com/explore?" + urlencode(params, quote_via=quote)


def read_games(csv_path: Path) -> list[tuple[str, str, date]]:
    """Read (game, publisher, release_date) rows from the CSV, skipping bad rows."""
    games = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{csv_path} is missing column(s): {', '.join(sorted(missing))}")

        for line_no, row in enumerate(reader, start=2):
            game = (row.get("game_name") or "").strip()
            publisher = (row.get("publisher_name") or "").strip()
            release = (row.get("alpha_release_date") or "").strip()

            if not (game or publisher or release):
                continue  # blank line
            if not game:
                print(f"Skipping line {line_no}: no game_name")
                continue
            try:
                release_date = datetime.strptime(release, "%Y-%m-%d").date()
            except ValueError:
                print(f"Skipping line {line_no} ({game}): bad date '{release}' (need YYYY-MM-DD)")
                continue

            games.append((game, publisher, release_date))
    return games


def make_links(games, geo="GB", months_before=MONTHS_BEFORE, months_after=MONTHS_AFTER):
    """Return a list of (label, url): game, publisher, game, publisher, ..."""
    today = date.today()
    links = []
    for game, publisher, release in games:
        start = add_months(release, -months_before)
        end = min(add_months(release, months_after), today)  # Trends can't look into the future
        if start >= end:
            print(f"Skipping {game}: its date window hasn't happened yet")
            continue

        links.append((game, build_url(game, start, end, geo)))
        if publisher:
            links.append((publisher, build_url(publisher, start, end, geo)))
    return links


def main() -> None:
    parser = argparse.ArgumentParser(description="Build (and open) Google Trends links from games.csv.")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="Path to games.csv")
    parser.add_argument("--out", type=Path, default=None, help="Where to write link.txt (default: next to the CSV)")
    parser.add_argument("--geo", default="GB", help="Country code (default: GB)")
    parser.add_argument("--before", type=int, default=MONTHS_BEFORE, help="Months before release (default: 3)")
    parser.add_argument("--after", type=int, default=MONTHS_AFTER, help="Months after release (default: 6)")
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between opening tabs (default: 2)")
    parser.add_argument("--no-open", action="store_true", help="Only write link.txt, don't open the browser")
    args = parser.parse_args()

    games = read_games(args.csv)
    links = make_links(games, args.geo, args.before, args.after)
    if not links:
        print("No links were made. Is games.csv filled in?")
        return

    out_path = args.out or args.csv.with_name("link.txt")
    out_path.write_text("\n".join(url for _, url in links) + "\n", encoding="utf-8")
    print(f"Wrote {len(links)} links for {len(games)} games to {out_path}")

    if args.no_open:
        return

    print(f"Opening in your browser, {args.delay}s apart. Ctrl+C to stop.")
    try:
        for i, (label, url) in enumerate(links, start=1):
            webbrowser.open_new_tab(url)
            print(f"  [{i}/{len(links)}] {label}")
            time.sleep(args.delay)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()