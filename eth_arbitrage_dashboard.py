# ================================================
# Crypto Arbitrage Dashboard - Multi Coin Version
# Made for Streamlit Cloud Deployment
# ================================================

import streamlit as st
import pandas as pd
import ccxt
import time
import requests
from datetime import datetime

# Shared area to track last alerts and prevent spam
if "last_alerts" not in st.session_state:
    st.session_state.last_alerts = {}

# Telegram Alert Function
def send_telegram_alert(message):
    token = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message}
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        st.warning(f"Telegram error: {e}")

# App configuration
st.set_page_config(page_title="Crypto Arbitrage Dashboard", layout="wide")

st.title("💱 Crypto Arbitrage Live Dashboard")
st.caption("Track real-time arbitrage opportunities across multiple exchanges and coins.")

# Sidebar settings
st.sidebar.header("⚙️ Settings")

# Select coins
coins = ["ETH", "BTC", "BNB", "SOL", "TON", "USDT", "ADA", "DOGE"]
selected_coin = st.sidebar.selectbox("Select Coin", coins)

# Fee simulation (percent)
taker_fee = st.sidebar.number_input("Taker Fee per Exchange (%)", 0.0, 2.0, 0.1)
transfer_fee_usd = st.sidebar.number_input("Approx Transfer Cost (USD)", 0.0, 20.0, 1.0)
profit_threshold = st.sidebar.number_input("Alert Profit Threshold (%)", 0.0, 10.0, 1.0)

# Exchanges to use
exchange_names = [
    "binance", "coinbase", "kraken", "kucoin", "okx",
    "gateio", "bitstamp", "bybit", "huobi"
]

st.sidebar.write(f"Tracking {len(exchange_names)} exchanges.")

# Load exchanges via ccxt
exchanges = {}
for name in exchange_names:
    try:
        exchanges[name] = getattr(ccxt, name)()
    except Exception:
        pass

# Get ticker prices
def get_prices(symbol):
    prices = {}
    for name, ex in exchanges.items():
        try:
            ticker = ex.fetch_ticker(symbol)
            bid = ticker.get("bid")
            ask = ticker.get("ask")
            if bid and ask:
                prices[name] = {"buy": ask, "sell": bid}
        except Exception:
            continue
    return prices

# Calculate arbitrage
def find_arbitrage(symbol):
    results = []
    prices = get_prices(symbol)
    for ex_buy, buy_data in prices.items():
        for ex_sell, sell_data in prices.items():
            if ex_buy == ex_sell:
                continue
            buy_price = buy_data["buy"] * (1 + taker_fee / 100)
            sell_price = sell_data["sell"] * (1 - taker_fee / 100)
            profit = ((sell_price - buy_price) / buy_price) * 100
            if profit > 0:
                results.append({
                    "Buy From": ex_buy,
                    "Sell On": ex_sell,
                    "Buy Price ($)": round(buy_price, 2),
                    "Sell Price ($)": round(sell_price, 2),
                    "Profit (%)": round(profit, 2)
                })
    return pd.DataFrame(results)

# Tabs
tab1, tab2 = st.tabs(["📈 Live Dashboard", "📜 History"])

# Live Dashboard
with tab1:
    st.subheader(f"🔹 {selected_coin}/USDT Arbitrage Opportunities")
    symbol = f"{selected_coin}/USDT"

    df = find_arbitrage(symbol)
    if not df.empty:
        df = df.sort_values("Profit (%)", ascending=False)
        st.dataframe(df, use_container_width=True)

        top = df.iloc[0]
        if top["Profit (%)"] >= profit_threshold:
            message = (f"💰 Arbitrage Alert: {selected_coin}\n"
                       f"Buy from: {top['Buy From']} @ ${top['Buy Price ($)']}\n"
                       f"Sell on: {top['Sell On']} @ ${top['Sell Price ($)']}\n"
                       f"Profit: {top['Profit (%)']}%")
            if st.session_state.last_alerts.get(selected_coin) != message:
                send_telegram_alert(message)
                st.session_state.last_alerts[selected_coin] = message

            # Save to history
            log = {
                "Timestamp": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "Coin": selected_coin,
                "Buy From": top["Buy From"],
                "Sell On": top["Sell On"],
                "Buy Price ($)": top["Buy Price ($)"],
                "Sell Price ($)": top["Sell Price ($)"],
                "Profit (%)": top["Profit (%)"]
            }
            history_df = pd.DataFrame([log])
            history_df.to_csv("arbitrage_history.csv", mode="a", index=False, header=False)

        st.info("Auto-refresh every 60 seconds. Streamlit Cloud may pause after inactivity.")
    else:
        st.warning("No price data available. Some exchanges may be temporarily unavailable.")

# History Tab
with tab2:
    st.subheader("📜 Past Arbitrage Alerts")
    try:
        history = pd.read_csv("arbitrage_history.csv", names=[
            "Timestamp", "Coin", "Buy From", "Sell On",
            "Buy Price ($)", "Sell Price ($)", "Profit (%)"
        ])
        st.dataframe(history.tail(50), use_container_width=True)
        st.download_button("Download Full History CSV", data=history.to_csv(index=False), file_name="arbitrage_history.csv")
    except FileNotFoundError:
        st.info("No history yet — alerts will be saved here.")

# Auto refresh
time.sleep(1)
