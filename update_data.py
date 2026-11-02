import os
import json
import time
from datetime import datetime, timezone
import pandas as pd
import requests

HISTORY_FILE = "history.json"

# Fetches the key from environment variables (GitHub Actions) or falls back to your local string
CG_API_KEY = os.environ.get("CG_API_KEY")

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


def fetch_recent_fng() -> dict:
    """Fetches the latest 14 days of Fear & Greed Index data."""
    url = "https://api.alternative.me/fng/?limit=14"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    fng_map = {}
    for item in resp.json().get("data", []):
        dt = datetime.fromtimestamp(int(item["timestamp"]), tz=timezone.utc).strftime("%Y-%m-%d")
        fng_map[dt] = int(item["value"])
    return fng_map


def fetch_coingecko_7d(coin_id: str, vs_currency: str) -> dict:
    """Fetches 7-day daily prices from CoinGecko using an API key."""
    url = (
        f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
        f"?vs_currency={vs_currency}&days=7&interval=daily"
    )
    
    headers = {
        "accept": "application/json",
        "x-cg-demo-api-key": CG_API_KEY
    }
    
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    prices = resp.json().get("prices", [])

    daily_map = {}
    for ts_ms, price in prices:
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")
        daily_map[dt] = float(price)

    # Sleep reduced from 7s to 2s since the API key affords higher rate limits
    time.sleep(2)
    return daily_map


def main():
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        db = json.load(f)

    fng_map = fetch_recent_fng()
    latest_fng_fallback = next(iter(fng_map.values()), 50)

    for ticker, meta in ASSETS.items():
        coin_id = meta["id"]
        print(f"Updating {ticker} ({coin_id})...")

        usd_map = fetch_coingecko_7d(coin_id, "usd")
        inr_map = fetch_coingecko_7d(coin_id, "inr")

        existing_records = db.get("assets", {}).get(ticker, {}).get("history", [])
        
        # Using a dictionary keyed by date guarantees data is overwritten/updated, never duplicated
        record_by_date = {r["date"]: r for r in existing_records}

        for dt, usd_val in usd_map.items():
            inr_val = inr_map.get(dt)
            if inr_val is None:
                continue
            fng_val = fng_map.get(dt, record_by_date.get(dt, {}).get("fng", latest_fng_fallback))
            record_by_date[dt] = {
                "date": dt,
                "close_usd": round(usd_val, 4),
                "close_inr": round(inr_val, 2),
                "drop_30d_pct": None,
                "fng": int(fng_val),
            }

        df = pd.DataFrame(list(record_by_date.values()))
        df = df.sort_values("date").reset_index(drop=True)

        df["drop_30d_pct"] = (
            (df["close_usd"] - df["close_usd"].shift(30))
            / df["close_usd"].shift(30)
            * 100.0
        ).round(2)

        updated_history = []
        for _, row in df.iterrows():
            updated_history.append(
                {
                    "date": row["date"],
                    "close_usd": float(row["close_usd"]),
                    "close_inr": float(row["close_inr"]),
                    "drop_30d_pct": None if pd.isna(row["drop_30d_pct"]) else float(row["drop_30d_pct"]),
                    "fng": int(row["fng"]),
                }
            )

        db.setdefault("assets", {})[ticker] = {
            "id": coin_id,
            "name": meta["name"],
            "history": updated_history,
        }

    db["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, separators=(",", ":"))
    print("Successfully updated history.json.")


if __name__ == "__main__":
    main()