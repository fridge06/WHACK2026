
import csv
import os
import time
import requests
from datetime import date, timedelta
from calendar import monthrange

INPUT_FILE = r"C:\Users\aayan\GitProjects\WHACK2026\data\games.csv"
OUTPUT_FILE = r"C:\Users\aayan\GitProjects\WHACK2026\data\raw\cap.csv"

CAP_URL = "https://api.bavest.co/v2/equities/market-cap"
PRICE_URL = "https://api.bavest.co/v2/timeseries/history"

API_KEY = input("API key: ")

HEADERS = {
    "Accept": "application/json",
    "x-api-key": API_KEY
}


def change_months(original_date, months):
    month = original_date.month - 1 + months
    year = original_date.year + month // 12
    month = month % 12 + 1
    day = min(original_date.day, monthrange(year, month)[1])

    return date(year, month, day)


def get_data(url, params):
    response = requests.get(
        url,
        params=params,
        headers=HEADERS,
        timeout=30
    )

    response.raise_for_status()
    return response.json()["data"]


def get_prices(ticker, start, end, currency):
    data = get_data(
        PRICE_URL,
        {
            "symbol": ticker,
            "from": str(start),
            "to": str(end),
            "currency": currency
        }
    )

    return data["prices"]


def main():
    if not API_KEY:
        print("Missing API key")
        return

    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    with open(INPUT_FILE, "r", newline="", encoding="utf-8-sig") as input_file:

        games = csv.DictReader(input_file)

        with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as output_file:

            columns = [
                "game_name",
                "company_stock_ticker",
                "alpha_release_date",
                "metric_date",
                "date",
                "closing_price",
                "shares_outstanding_est",
                "market_cap",
                "currency",
                "status"
            ]

            writer = csv.DictWriter(output_file, fieldnames=columns)
            writer.writeheader()

            for game in games:

                game_name = game["game_name"].strip()
                ticker = game["company_stock_ticker"].strip()
                alpha_date = game["alpha_release_date"].strip()

                print("\nGetting data for:", game_name, "-", ticker)

                try:
                    if not ticker or not alpha_date:
                        raise ValueError("Missing ticker or alpha date")

                    alpha_date = date.fromisoformat(alpha_date[:10])

                    start_date = change_months(alpha_date, -3)
                    end_date = change_months(alpha_date, 6)

                    print("Period:", start_date, "to", end_date)

                    # Get latest market capitalisation
                    cap_data = get_data(
                        CAP_URL,
                        {"symbol": ticker}
                    )

                    market_cap = cap_data["metricValue"]
                    currency = cap_data["metricCurrency"]
                    metric_date = date.fromisoformat(
                        cap_data["metricDate"][:10]
                    )

                    # Get closing price on the market cap observation date
                    baseline_prices = get_prices(
                        ticker,
                        metric_date - timedelta(days=14),
                        metric_date,
                        currency
                    )

                    if not baseline_prices:
                        raise ValueError("No baseline price available")

                    baseline_price = baseline_prices[-1]["close"]

                    if not baseline_price:
                        raise ValueError("Invalid baseline price")

                    # Estimate shares outstanding
                    shares = market_cap / baseline_price

                    print("Estimated shares:", round(shares, 2))

                    # Get all daily prices in the requested period
                    prices = get_prices(
                        ticker,
                        start_date,
                        end_date,
                        currency
                    )

                    count = 0

                    for point in prices:

                        closing_price = point["close"]

                        if closing_price is None:
                            continue

                        estimated_cap = closing_price * shares

                        writer.writerow({
                            "game_name": game_name,
                            "company_stock_ticker": ticker,
                            "alpha_release_date": alpha_date,
                            "metric_date": metric_date,
                            "date": point["date"],
                            "closing_price": closing_price,
                            "shares_outstanding_est": shares,
                            "market_cap": estimated_cap,
                            "currency": currency,
                            "status": "Estimated"
                        })

                        count += 1

                    print("Saved", count, "daily observations")

                    if count == 0:
                        print("No historical prices returned")

                except requests.exceptions.RequestException as error:
                    print("API error:", error)

                except (KeyError, ValueError, TypeError, IndexError) as error:
                    print("Data error:", error)

                output_file.flush()
                time.sleep(0.5)

    print("\nFinished. Saved data to:", OUTPUT_FILE)


if __name__ == "__main__":
    main()
