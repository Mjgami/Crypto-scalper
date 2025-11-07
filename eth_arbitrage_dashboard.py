""" Multi-Coin Multi-Exchange Arbitrage Dashboard Streamlit app that:

Monitors chosen coins across selected exchanges (via ccxt) for arbitrage

Shows buy/sell prices per exchange (adjusted for fees)

Logs alert history to CSV and shows a History tab

Sends Telegram alerts when profit% threshold exceeded


How to use:

Install dependencies: pip install streamlit ccxt pandas requests

Save this file as eth_multi_arbitrage_dashboard.py and push to GitHub

Set STREAMLIT secrets or environment variables: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (optional)

Deploy on Streamlit Cloud or run locally: streamlit run eth_multi_arbitrage_dashboard.py


Notes:

Public price fetching uses ccxt public endpoints; no API keys required for tickers

Fees are configurable per-exchange in the sidebar (taker fee %)

"Hidden charges" are modeled as: taker_fee_percent + optional transfer_fee_usd

Persisted history: arbitrage_history.csv in app folder (works on Streamlit Cloud but may be ephemeral) """


import streamlit as st import ccxt import pandas as pd import time import os import json import requests from datetime import datetime from pathlib import Path

-------------------- Configuration --------------------

DEFAULT_EXCHANGES = [ "binance", "coinbasepro", "kraken", "kucoin", "okx", "gate", "bitstamp", "huobipro", "bybit", ]

DEFAULT_COINS = ["ETH", "BTC", "BNB", "SOL", "TON", "USDT", "ADA", "DOGE"] QUOTE_PREFERENCES = ["USDT", "USD", "BTC"]  # try in this order when resolving symbols

HISTORY_FILE = Path("arbitrage_history.csv")

Pre-set example taker fee percentages (these are placeholders; edit in sidebar)

DEFAULT_FEES = { "binance": 0.001,      # 0.1% "coinbasepro": 0.005,  # 0.5% "kraken": 0.0026,      # 0.26% "kucoin": 0.001,       # 0.1% "okx": 0.001,          # 0.1% "gate": 0.002,         # 0.2% "bitstamp": 0.005,     # 0.5% "huobipro": 0.002,     # 0.2% "bybit": 0.001,        # 0.1% }

-------------------- Helper functions --------------------

def load_history(): if HISTORY_FILE.exists(): try: return pd.read_csv(HISTORY_FILE, parse_dates=["timestamp"])  # timestamp column except Exception: return pd.DataFrame() return pd.DataFrame()

def save_history(df): try: df.to_csv(HISTORY_FILE, index=False) except Exception as e: st.warning(f"Could not save history: {e}")

def append_history(record): df = load_history() df = pd.concat([df, pd.DataFrame([record])], ignore_index=True) save_history(df)

def get_exchange_instance(name): try: if not hasattr(ccxt, name): return None exchange_cls = getattr(ccxt, name) # instantiate with rateLimit true to be polite exchange = exchange_cls({"enableRateLimit": True}) return exchange except Exception: return None

def resolve_symbol(exchange, base): """Try to find a tradable symbol for base with preferred quotes""" markets = {} try: markets = exchange.load_markets() except Exception: return None

for q in QUOTE_PREFERENCES:
    symbol = f"{base}/{q}"
    if symbol in markets:
        return symbol
# try any market that startswith base/
for s in markets.keys():
    if s.startswith(base + "/"):
        return s
return None

def fetch_price_for_exchange(exchange_name, coin): exchange = get_exchange_instance(exchange_name) if not exchange: return None symbol = None try: symbol = resolve_symbol(exchange, coin) if not symbol: return None ticker = exchange.fetch_ticker(symbol) # ccxt ticker has bid (highest buy) and ask (lowest sell) and last bid = ticker.get("bid") ask = ticker.get("ask") last = ticker.get("last") return {"exchange": exchange_name, "symbol": symbol, "bid": bid, "ask": ask, "last": last} except Exception: return None

def send_telegram(message): token = os.getenv("TELEGRAM_BOT_TOKEN") or (st.secrets.get("TELEGRAM_BOT_TOKEN") if "TELEGRAM_BOT_TOKEN" in st.secrets else None) chat_id = os.getenv("TELEGRAM_CHAT_ID") or (st.secrets.get("TELEGRAM_CHAT_ID") if "TELEGRAM_CHAT_ID" in st.secrets else None) if not token or not chat_id: return False, "No Telegram credentials" url = f"https://api.telegram.org/bot{token}/sendMessage" payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"} try: r = requests.post(url, json=payload, timeout=10) return (r.status_code == 200), r.text except Exception as e: return False, str(e)

-------------------- Streamlit UI --------------------

st.set_page_config(page_title="Multi-Coin Arbitrage Dashboard", layout="wide") st.title("🚀 Multi-Coin Multi-Exchange Arbitrage Dashboard") st.caption("Live prices via CCXT • Configure exchanges & fees in sidebar • History of alerts stored locally")

Sidebar controls

with st.sidebar: st.header("Settings") exchanges = st.multiselect("Exchanges to monitor", options=sorted(set(DEFAULT_EXCHANGES)), default=DEFAULT_EXCHANGES) coins = st.multiselect("Coins / Symbols", options=DEFAULT_COINS, default=["ETH"])  # default show ETH tab first refresh_interval = st.number_input("Refresh interval (seconds)", min_value=10, max_value=600, value=60, step=5) profit_threshold = st.number_input("Alert profit threshold (%)", min_value=0.1, max_value=20.0, value=0.5, step=0.1)

st.markdown("---")
st.subheader("Exchange Fee Overrides (taker %)")
fee_overrides = {}
for ex in exchanges:
    default_fee = DEFAULT_FEES.get(ex, 0.002)  # default 0.2% if unknown
    fee_overrides[ex] = st.number_input(f"{ex} taker fee %", min_value=0.0, max_value=5.0, value=float(default_fee * 100.0)) / 100.0

st.markdown("---")
st.subheader("Hidden / Transfer Fees (optional)")
transfer_fee_usd = st.number_input("Estimated transfer cost in USD (per transfer)", min_value=0.0, value=5.0, step=0.5)

st.markdown("---")
st.info("Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Streamlit Secrets or as environment variables to enable alerts.")
if st.button("Force Save Current Settings to session"):
    st.session_state['saved_settings'] = {
        'exchanges': exchanges,
        'coins': coins,
        'refresh_interval': refresh_interval,
        'profit_threshold': profit_threshold,
        'fee_overrides': fee_overrides,
        'transfer_fee_usd': transfer_fee_usd,
    }
    st.success("Settings saved in session")

Main layout: tabs for each coin + History tab

tabs = st.tabs(coins + ["History"])

Shared area to track last_alerts so we don't spam

if 'last_alerts' not in st.session_state: st.session_state['last_alerts'] = {}

We'll iterate over tabs and populate content

for i, coin in enumerate(coins): with tabs[i]: st.subheader(f"{coin} Markets") col1, col2 = st.columns([3,1]) with col2: st.metric("Monitored Exchanges", len(exchanges)) st.metric("Refresh (s)", refresh_interval) st.metric("Alert Threshold (%)", f"{profit_threshold:.2f}")

status_placeholder = st.empty()
    table_placeholder = st.empty()

    # Fetch data for coin across exchanges
    records = []
    status_msgs = []
    for ex in exchanges:
        res = fetch_price_for_exchange(ex, coin)
        if res:
            # Calculate adjusted buy (ask) and sell (bid) taking into account taker fees
            fee = fee_overrides.get(ex, 0.002)
            bid = res.get('bid')
            ask = res.get('ask')
            last = res.get('last')
            # If bid or ask missing, fallback to last
            if bid is None and last is not None:
                bid = last
            if ask is None and last is not None:
                ask = last
            if bid is None or ask is None:
                status_msgs.append(f"{ex}: no bid/ask")
                continue

            # Effective prices after trading fees
            effective_buy = ask * (1 + fee)   # price you'd pay when buying (including taker fee)
            effective_sell = bid * (1 - fee)  # net you'd receive when selling (after fee)

            # Convert transfer_fee_usd to quote currency if quote isn't USD/USDT
            # For simplicity, we assume quote is USD/USDT; otherwise leave as-is
            records.append({
                'exchange': ex,
                'symbol': res.get('symbol'),
                'ask': ask,
                'bid': bid,
                'effective_buy': effective_buy,
                'effective_sell': effective_sell,
                'fee%': fee * 100.0,
            })
        else:
            status_msgs.append(f"{ex}: no data")

    if len(records) == 0:
        status_placeholder.error("No market data available for selected exchanges/coin. Check exchanges or lower refresh.")
        continue

    df = pd.DataFrame(records)
    # Sort by effective_buy ascending (cheapest to buy)
    df_sorted_buy = df.sort_values('effective_buy')
    df_sorted_sell = df.sort_values('effective_sell', ascending=False)

    # Show table and best buy/sell
    table_placeholder.dataframe(df[['exchange','symbol','ask','bid','fee%','effective_buy','effective_sell']].sort_values('effective_buy'), use_container_width=True)

    best_buy = df_sorted_buy.iloc[0]
    best_sell = df_sorted_sell.iloc[0]

    profit_per_unit = best_sell['effective_sell'] - best_buy['effective_buy'] - transfer_fee_usd
    profit_percent = (profit_per_unit / best_buy['effective_buy']) * 100.0

    st.markdown("---")
    st.markdown("### Best current opportunity (after fees & transfer cost)")
    st.write(f"Buy on **{best_buy['exchange']}** at **{best_buy['effective_buy']:.6f}** ({best_buy['symbol']})")
    st.write(f"Sell on **{best_sell['exchange']}** at **{best_sell['effective_sell']:.6f}** ({best_sell['symbol']})")
    st.write(f"Estimated net profit per unit (USD-equivalent): **{profit_per_unit:.6f}**")
    st.write(f"Estimated profit percentage: **{profit_percent:.4f}%**")

    # Alerting logic
    alert_needed = profit_percent > profit_threshold
    key = f"{coin}_{best_buy['exchange']}_{best_sell['exchange']}_{int(best_buy['effective_buy'])}_{int(best_sell['effective_sell'])}"

    if alert_needed and st.session_state['last_alerts'].get(key) != True:
        # Build message
        msg = (
            f"*Arbitrage Alert - {coin}*\n"
            f"Buy: {best_buy['exchange']} at {best_buy['effective_buy']:.6f} ({best_buy['symbol']})\n"
            f"Sell: {best_sell['exchange']} at {best_sell['effective_sell']:.6f} ({best_sell['symbol']})\n"
            f"Profit/unit: {profit_per_unit:.6f} USD\n"
            f"Profit %: {profit_percent:.4f}%\n"
            f"Timestamp: {datetime.utcnow().isoformat()} UTC"
        )
        ok, info = send_telegram(msg)
        if ok:
            st.success(f"Telegram alert sent for {coin}!")
        else:
            st.warning(f"Telegram not sent: {info}")

        # Save to history file
        record = {
            'timestamp': datetime.utcnow().isoformat(),
            'coin': coin,
            'buy_exchange': best_buy['exchange'],
            'buy_price': best_buy['effective_buy'],
            'sell_exchange': best_sell['exchange'],
            'sell_price': best_sell['effective_sell'],
            'profit_usd': profit_per_unit,
            'profit_percent': profit_percent,
        }
        append_history(record)
        st.session_state['last_alerts'][key] = True

    if len(status_msgs) > 0:
        status_placeholder.info("; ".join(status_msgs))

History tab

with tabs[len(coins)]: st.subheader("Alert History") hist = load_history() if hist.empty: st.write("No alerts yet. Alerts that meet the threshold will be logged here.") else: # Show most recent first hist = hist.sort_values('timestamp', ascending=False) st.dataframe(hist, use_container_width=True) if st.button("Download history as CSV"): st.download_button("Download CSV", data=hist.to_csv(index=False).encode('utf-8'), file_name="arbitrage_history.csv", mime="text/csv")

Auto-refresh behavior

st.markdown("---") st.caption("App auto-refresh: press the ▶️ Run button or rely on Streamlit's rerun. For continuous auto-run locally, run the script with a process manager.")

NOTE: We intentionally do NOT run an infinite loop in Streamlit main script because Streamlit's lifecycle handles reruns.

Instead, the user can set browser auto-refresh or use Streamlit's experimental features. If you want continuous background fetching,

consider deploying a small worker process and writing to a shared DB or file.

""
