# =========================
#  CRYPTO ARBITRAGE DASHBOARD
#ersion======================

import streamlit as st
import pandas as pd
import ccxt
import requests
import time
from datetime import datetime

# =========================
#  SETTINGS
# =========================

st.set_page_config(page_title="Crypto Arbitrage Dashboard", layout="wide")
st.title("💰 Crypto Arbitrage Dashboard")
st.caption("Find profitable price gaps between exchanges in real time")

# Your Telegram Bot token and Chat ID (set these in Streamlit Secrets or replace manually)
TELEGRAM_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", "")

# =========================
#  GLOBALS
# =========================

if "history" not in st.session_state:
    st.session_state.history = []

if "last_alerts" not in st.session_state:
    st.session_state.last_alerts = {}

# =========================
#  HELPER FUNCTIONS
# =========================

@st.cache_data(ttl=600)
def load_exchanges():
    """Load all ccxt exchanges (around 140+)"""
    exchange_ids = ccxt.exchanges
    exchanges = {}
    for ex_id in exchange_ids:
        try:
            exchanges[ex_id] = getattr(ccxt, ex_id)()
        except Exception:
            continue
    return exchanges

def get_prices(symbol, exchanges):
    """Fetch prices from multiple exchanges"""
    prices = {}
    fallback_symbol = symbol.replace("USDT", "USD")
    for name, ex in exchanges.items():
        try:
            ex.load_markets()
            if symbol in ex.symbols:
                ticker = ex.fetch_ticker(symbol)
            elif fallback_symbol in ex.symbols:
                ticker = ex.fetch_ticker(fallback_symbol)
            else:
                continue
            prices[name] = {
                "bid": ticker.get("bid"),
                "ask": ticker.get("ask"),
                "last": ticker.get("last"),
            }
        except Exception:
            continue
    return prices

def send_telegram_message(text):
    """Send alert to Telegram"""
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
            requests.post(url, data=data)
        except:
            pass

def find_arbitrage(prices):
    """Find best buy/sell opportunity"""
    if not prices:
        return None

    df = pd.DataFrame(prices).T
    df = df.dropna(subset=["bid", "ask"])
    if df.empty:
        return None

    min_ask = df["ask"].min()
    max_bid = df["bid"].max()
    buy_ex = df["ask"].idxmin()
    sell_ex = df["bid"].idxmax()
    profit = ((max_bid - min_ask) / min_ask) * 100

    return {
        "buy_ex": buy_ex,
        "sell_ex": sell_ex,
        "buy_price": min_ask,
        "sell_price": max_bid,
        "profit": profit,
    }

# =========================
#  MAIN DASHBOARD
# =========================

coins = ["BTC", "ETH", "BNB", "SOL", "TON", "USDT", "XRP", "ADA", "DOGE", "DOT"]
tabs = st.tabs(coins)

exchanges = load_exchanges()

for i, coin in enumerate(coins):
    with tabs[i]:
        st.subheader(f"{coin}/USDT Arbitrage Tracker")
        symbol = f"{coin}/USDT"

        prices = get_prices(symbol, exchanges)

        if not prices:
            st.warning("⚠️ No price data available — some exchanges may not support this pair.")
            continue

        df = pd.DataFrame(prices).T
        st.dataframe(df, width='stretch')

        arb = find_arbitrage(prices)
        if arb:
            st.success(
                f"💹 Buy {coin} from **{arb['buy_ex']}** at **${arb['buy_price']:.2f}**, "
                f"Sell on **{arb['sell_ex']}** at **${arb['sell_price']:.2f}** → Profit: **{arb['profit']:.2f}%**"
            )

            alert_id = f"{coin}_{arb['buy_ex']}_{arb['sell_ex']}"
            if arb["profit"] > 1.0 and alert_id not in st.session_state.last_alerts:
                msg = f"🚨 {coin} Arbitrage Alert!\nBuy on {arb['buy_ex']} (${arb['buy_price']:.2f})\nSell on {arb['sell_ex']} (${arb['sell_price']:.2f})\nProfit: {arb['profit']:.2f}%"
                send_telegram_message(msg)
                st.session_state.last_alerts[alert_id] = datetime.now()
                st.session_state.history.append(msg)
        else:
            st.info("No profitable arbitrage found at this time.")

# =========================
#  HISTORY TAB
# =========================

st.markdown("---")
st.subheader("📜 Alert History")
if st.session_state.history:
    for alert in reversed(st.session_state.history[-30:]):
        st.text(alert)
else:
    st.info("No past alerts yet.")
