import os
import json
from datetime import datetime, timezone
import pandas as pd
import requests

ASSETS = {
    "BTC": {"id": "bitcoin", "name": "Bitcoin"},
    "ETH": {"id": "ethereum", "name": "Ethereum"},
    "SOL": {"id": "solana", "name": "Solana"},
    "BNB": {"id": "binancecoin", "name": "BNB"},
    "XRP": {"id": "ripple", "name": "XRP"},
    "LINK": {"id": "chainlink", "name": "Chainlink"},
    "LTC": {"id": "litecoin", "name": "Litecoin"},
    "INJ": {"id": "injective-protocol", "name": "Injective"},
    "QNT": {"id": "quant-network", "name": "Quant"},
    "AAVE": {"id": "aave", "name": "Aave"},
}

CSV_DIR = "./csv_data"
OUTPUT_FILE = "history.json"


def fetch_usd_inr_rates() -> pd.Series:
    """Fetches daily USD to INR rates since 2018-01-01 and forward-fills weekends/holidays."""
    url = "https://api.frankfurter.app/2018-01-01..?from=USD&to=INR"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("rates", {})

    records = {date_str: val.get("INR") for date_str, val in data.items() if "INR" in val}
    series = pd.Series(records, dtype=float)
    series.index = pd.to_datetime(series.index)
    series = series.sort_index()

    full_idx = pd.date_range(
        start="2018-01-01",
        end=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        freq="D",
    )
    series = series.reindex(full_idx).ffill().bfill()
    series.index = series.index.strftime("%Y-%m-%d")
    return series


def fetch_fear_and_greed() -> dict:
    """Fetches full historical Fear & Greed Index mapped to YYYY-MM-DD."""
    url = "https://api.alternative.me/fng/?limit=0"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    raw_list = resp.json().get("data", [])

    fng_map = {}
    for item in raw_list:
        ts = int(item["timestamp"])
        date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
        fng_map[date_str] = int(item["value"])
    return fng_map


def load_or_fetch_asset_csv(ticker: str) -> pd.DataFrame:
    """Reads ./csv_data/Binance_{TICKER}USDT_d.csv or logs a message if missing."""
    csv_path = os.path.join(CSV_DIR, f"Binance_{ticker}USDT_d.csv")

    if not os.path.exists(csv_path):
        print(f"[{ticker}] Couldn't fetch data: local CSV missing at {csv_path} and CryptoCompare free API is deprecated.")
        return pd.DataFrame()

    print(f"[{ticker}] Loading local CSV from {csv_path}...")
    df = pd.read_csv(csv_path, skiprows=1)
    df.columns = [c.strip().lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"], format="mixed").dt.strftime("%Y-%m-%d")
    df = df[["date", "close"]].rename(columns={"close": "close_usd"})

    df = df.drop_duplicates(subset=["date"], keep="last")
    df = df[df["date"] >= "2018-01-01"].sort_values("date").reset_index(drop=True)
    return df


def main():
    print("Fetching historical USD to INR exchange rates...")
    inr_rates = fetch_usd_inr_rates()
    default_inr = float(inr_rates.iloc[-1])

    print("Fetching historical Fear & Greed Index...")
    fng_map = fetch_fear_and_greed()

    output_payload = {
        "last_updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "assets": {},
    }

    for ticker, meta in ASSETS.items():
        df = load_or_fetch_asset_csv(ticker)
        if df.empty:
            continue

        df["inr_rate"] = df["date"].map(inr_rates).fillna(default_inr)
        df["close_inr"] = (df["close_usd"] * df["inr_rate"]).round(2)
        df["close_usd"] = df["close_usd"].round(4)

        df["drop_30d_pct"] = (
            (df["close_usd"] - df["close_usd"].shift(30))
            / df["close_usd"].shift(30)
            * 100.0
        ).round(2)

        df["fng"] = df["date"].map(fng_map)
        df["fng"] = df["fng"].ffill().bfill().fillna(50).astype(int)

        records = []
        for _, row in df.iterrows():
            records.append(
                {
                    "date": row["date"],
                    "close_usd": float(row["close_usd"]),
                    "close_inr": float(row["close_inr"]),
                    "drop_30d_pct": None if pd.isna(row["drop_30d_pct"]) else float(row["drop_30d_pct"]),
                    "fng": int(row["fng"]),
                }
            )

        output_payload["assets"][ticker] = {
            "id": meta["id"],
            "name": meta["name"],
            "history": records,
        }
        print(f"[{ticker}] Processed {len(records)} daily records.")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, separators=(",", ":"))
    print(f"Saved seeded dataset to {OUTPUT_FILE}.")


if __name__ == "__main__":
    main()