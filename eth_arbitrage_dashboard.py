import streamlit as st
import requests
import pandas as pd
import time
import os

# ========== CONFIGURATION ==========
COINGECKO_API = "https://api.coingecko.com/api/v3/coins/ethereum/tickers"
REFRESH_INTERVAL = 60  # seconds between updates

# Telegram credentials (set as Streamlit secrets or environment variables)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or st.secrets.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or st.secrets.get("TELEGRAM_CHAT_ID")

# ========== FUNCTIONS ==========

def fetch_prices():
    """Fetch ETH prices from CoinGecko (hundreds of exchanges)."""
    response = requests.get(COINGECKO_API, timeout=15)
    data = response.json().get("tickers", [])
    records = []
    for t in data:
        market = t["market"]["name"]
        base = t["base"]
        target = t["target"]
        last = t["last"]
        if target in ["USD", "USDT", "BUSD"]:
            records.append({
                "Exchange": market,
                "Pair": f"{base}/{target}",
                "Price (USD)": last
            })
    df = pd.DataFrame(records)
    return df

def send_telegram_alert(message):
    """Send alert to Telegram."""
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
        try:
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            st.warning(f"⚠️ Telegram alert failed: {e}")

# ========== DASHBOARD UI ==========

st.set_page_config(page_title="ETH Arbitrage Dashboard", layout="wide")
st.title("💹 Live Ethereum Arbitrage Dashboard")
st.caption("Data via CoinGecko • Auto-refresh every 60s • Alerts via Telegram")

# Initial placeholders
table_placeholder = st.empty()
alert_placeholder = st.empty()

last_alert = None

while True:
    df = fetch_prices()
    if df.empty:
        st.error("Failed to load price data. Try again later.")
        break

    df = df.sort_values("Price (USD)")
    buy = df.iloc[0]
    sell = df.iloc[-1]

    profit = sell["Price (USD)"] - buy["Price (USD)"]
    profit_percent = (profit / buy["Price (USD)"]) * 100

    table_placeholder.dataframe(df, use_container_width=True)

    alert_text = (
        f"🪙 *ETH Arbitrage Alert!*\n"
        f"Buy on: *{buy['Exchange']}* at `${buy['Price (USD)']:.2f}`\n"
        f"Sell on: *{sell['Exchange']}* at `${sell['Price (USD)']:.2f}`\n"
        f"💰 Profit: `${profit:.2f}` ({profit_percent:.2f}%) per ETH"
    )

    alert_placeholder.markdown(alert_text)

    # Send Telegram alert only if profit > 0.5% and it's new
    if profit_percent > 0.5 and alert_text != last_alert:
        send_telegram_alert(alert_text)
        last_alert = alert_text

    time.sleep(REFRESH_INTERVAL)
    st.rerun()
