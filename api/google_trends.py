
import pandas as pd
from pytrends.request import TrendReq
from pathlib import Path
import time


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

MONTHS_BEFORE_RELEASE = 3
MONTHS_AFTER_RELEASE = 6

REQUEST_DELAY = 2


# --------------------------------------------------
# FILE PATHS
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

GAMES_FILE = BASE_DIR / "data" / "games.csv"

GAME_OUTPUT_FILE = BASE_DIR / "data" / "raw" / "google_trends_games.csv"
PUBLISHER_OUTPUT_FILE = BASE_DIR / "data" / "raw" / "google_trends_publishers.csv"


# --------------------------------------------------
# GOOGLE TRENDS CONNECTION
# --------------------------------------------------

pytrends = TrendReq(
    hl="en-GB",
    tz=0,
    retries=2,
    backoff_factor=0.5
)


# --------------------------------------------------
# RETRIEVE SEARCH DATA
# --------------------------------------------------

def retrieve_search_data(search_term, start_date, end_date):

    start = start_date.strftime("%Y-%m-%d")
    end = end_date.strftime("%Y-%m-%d")

    timeframe = f"{start} {end}"

    print(f"Searching: {search_term}")
    print(f"Period: {timeframe}")

    pytrends.build_payload(
        [search_term],
        timeframe=timeframe,
        geo=""
    )

    search_data = pytrends.interest_over_time()

    if search_data.empty:
        print(f"No data returned for {search_term}.")
        return None

    # Remove partial-data indicator
    if "isPartial" in search_data.columns:
        search_data = search_data.drop(columns=["isPartial"])

    # Keep search-interest values
    search_data = search_data[[search_term]]

    # Rename column
    search_data = search_data.rename(
        columns={search_term: "search_interest"}
    )

    # Move date index into a column
    search_data.index.name = "date"
    search_data = search_data.reset_index()

    # Standardise date format
    search_data["date"] = pd.to_datetime(
        search_data["date"]
    ).dt.strftime("%Y-%m-%d")

    return search_data


# --------------------------------------------------
# MAIN FUNCTION
# --------------------------------------------------

def get_google_trends():

    games = pd.read_csv(GAMES_FILE)

    required_columns = [
        "game_name",
        "publisher_name",
        "release_date"
    ]

    for column in required_columns:
        if column not in games.columns:
            raise ValueError(f"Missing column in games.csv: {column}")

    all_game_data = []
    all_publisher_data = []

    for index, game in games.iterrows():

        game_name = game["game_name"]
        publisher_name = game["publisher_name"]

        release_date = pd.to_datetime(
            game["release_date"],
            errors="coerce"
        )

        if pd.isna(release_date):
            print(f"Invalid release date for {game_name}. Skipping.")
            continue

        # Calculate search timeframe
        start_date = release_date - pd.DateOffset(
            months=MONTHS_BEFORE_RELEASE
        )

        end_date = release_date + pd.DateOffset(
            months=MONTHS_AFTER_RELEASE
        )

        print("\n------------------------------------")
        print(f"Processing: {game_name}")
        print(f"Publisher: {publisher_name}")
        print("------------------------------------")

        # ------------------------------------------
        # GAME POPULARITY
        # ------------------------------------------

        try:

            game_data = retrieve_search_data(
                game_name,
                start_date,
                end_date
            )

            if game_data is not None:

                game_data.insert(0, "game_name", game_name)

                all_game_data.append(game_data)

                print("Game popularity retrieved.")

        except Exception as error:

            print(f"Game search error: {error}")

        time.sleep(REQUEST_DELAY)

        # ------------------------------------------
        # PUBLISHER POPULARITY
        # ------------------------------------------

        try:

            publisher_data = retrieve_search_data(
                publisher_name,
                start_date,
                end_date
            )

            if publisher_data is not None:

                publisher_data.insert(
                    0,
                    "publisher_name",
                    publisher_name
                )

                publisher_data.insert(
                    0,
                    "game_name",
                    game_name
                )

                all_publisher_data.append(publisher_data)

                print("Publisher popularity retrieved.")

        except Exception as error:

            print(f"Publisher search error: {error}")

        time.sleep(REQUEST_DELAY)

    # --------------------------------------------------
    # SAVE GAME POPULARITY
    # --------------------------------------------------

    if all_game_data:

        final_game_data = pd.concat(
            all_game_data,
            ignore_index=True
        )

        GAME_OUTPUT_FILE.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        final_game_data.to_csv(
            GAME_OUTPUT_FILE,
            index=False
        )

        print(f"\nGame data saved: {GAME_OUTPUT_FILE}")

    else:

        print("\nNo game popularity data retrieved.")

    # --------------------------------------------------
    # SAVE PUBLISHER POPULARITY
    # --------------------------------------------------

    if all_publisher_data:

        final_publisher_data = pd.concat(
            all_publisher_data,
            ignore_index=True
        )

        PUBLISHER_OUTPUT_FILE.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        final_publisher_data.to_csv(
            PUBLISHER_OUTPUT_FILE,
            index=False
        )

        print(f"Publisher data saved: {PUBLISHER_OUTPUT_FILE}")

    else:

        print("\nNo publisher popularity data retrieved.")

    print("\n------------------------------------")
    print("GOOGLE TRENDS COLLECTION COMPLETE")
    print("------------------------------------")


# --------------------------------------------------
# RUN SCRIPT
# --------------------------------------------------

if __name__ == "__main__":
    get_google_trends()
