
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt


def find_company(search_term):

    # Search Yahoo Finance using a company name or ticker
    search = yf.Search(
        search_term,
        max_results=10,
        news_count=0,
        lists_count=0
    )

    results = search.quotes

    # Only keep publicly traded companies
    companies = []

    for result in results:

        if result.get("quoteType") == "EQUITY":
            companies.append(result)

    if len(companies) == 0:
        print("No publicly traded companies found.")
        return None

    # Display possible matches
    print("\nPossible matches:")

    for i, company in enumerate(companies):

        name = company.get("longname", company.get("shortname", "Unknown"))
        ticker = company.get("symbol", "Unknown")
        exchange = company.get("exchange", "Unknown")

        print(f"{i + 1}. {name} ({ticker}) - {exchange}")

    # Let the user select the correct company
    choice = int(input("\nSelect company number: "))

    if choice < 1 or choice > len(companies):
        print("Invalid selection.")
        return None

    return companies[choice - 1]


def get_stock_history(company, start_date, end_date):

    ticker = company["symbol"]

    print(f"\nDownloading stock data for {ticker}...")

    stock = yf.Ticker(ticker)

    history = stock.history(
        start=start_date,
        end=end_date,
        interval="1d",
        auto_adjust=True
    )

    if history.empty:
        print("No historical stock data found.")
        return None

    # Keep the columns relevant to the project
    history = history[["Close", "Volume"]]

    history.index.name = "Date"

    print("\nStock history:")
    print(history)

    return history


def plot_stock_history(history, company):

    ticker = company["symbol"]
    name = company.get("longname", ticker)

    plt.figure(figsize=(12, 6))

    plt.plot(
        history.index,
        history["Close"],
        label="Stock Price"
    )

    plt.title(f"{name} ({ticker}) - Historical Stock Price")
    plt.xlabel("Date")
    plt.ylabel("Share Price")

    plt.grid(True)
    plt.legend()

    plt.tight_layout()
    plt.show()


def main():

    search_term = input("Enter publisher name or ticker: ")

    start_date = input("Start date (YYYY-MM-DD): ")
    end_date = input("End date (YYYY-MM-DD): ")

    company = find_company(search_term)

    if company is None:
        return

    history = get_stock_history(
        company,
        start_date,
        end_date
    )

    if history is None:
        return

    # Export the data
    filename = company["symbol"] + "_stock_history.csv"

    history.to_csv(filename)

    print(f"\nData saved to {filename}")

    # Display graph
    plot_stock_history(history, company)


if __name__ == "__main__":
    main()
