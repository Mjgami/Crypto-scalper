# ==========================
# eth_arbitrage_dashboard.py
# Crypto Arbitrage Dashboard (fixed)
# Deploy on Streamlit Cloud
# ==========================

import streamlit as st
import pandas as pd
import ccxt
import requests
import time
import os
from datetime import datetime
from pathlib import Path

# --------- Config / Constants ----------
HISTORY_FILE = Path("arbitrage_history.csv")
DEFAULT_EXCHANGES = [
    "binance", "coinbasepro", "kraken", "kucoin", "okx",
    "gate", "bitstamp", "bybit", "huobipro", "mexc",
    "bitget", "bitmart", "lbank", "whitebit", "coinex"
]
QUOTE_PREFERENCES = ["USDT", "USD", "BTC", "ETH"]
COMMON_COINS = ["BTC", "ETH", "BNB", "SOL", "TON", "ADA", "DOGE", "XRP", "DOT"]

# --------- Streamlit page setup ----------
st.set_page_config(page_title="Crypto Arbitrage Dashboard", layout="wide")
st.title("🚀 Crypto Arbitrage Dashboard — Fixed & Stable")
st.caption("Live price gaps across exchanges. Use the controls to select coins/exchanges. Add Telegram credentials in Secrets to receive alerts.")

# --------- Secrets / Telegram ----------
TELEGRAM_BOT_TOKEN = st.secrets.get("TELEGRAM_BOT_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN", ""))
TELEGRAM_CHAT_ID = st.secrets.get("TELEGRAM_CHAT_ID", os.getenv("TELEGRAM_CHAT_ID", ""))

# --------- Session state init ----------
if "last_alerts" not in st.session_state:
    st.session_state["last_alerts"] = {}
if "exchanges_cache" not in st.session_state:
    st.session_state["exchanges_cache"] = {}
if "markets_loaded" not in st.session_state:
    st.session_state["markets_loaded"] = set()

# --------- Sidebar controls ----------
with st.sidebar:
    st.header("Settings")
    coin = st.selectbox("Coin", COMMON_COINS, index=1)  # default ETH
    ask_refresh = st.button("Refresh Now")
    auto_refresh = st.checkbox("Auto refresh every N seconds", value=False)
    refresh_interval = st.number_input("Auto refresh interval (seconds)", min_value=10, max_value=600, value=60, step=5)

    st.markdown("---")
    st.subheader("Exchanges to monitor")
    st.write("Default selection are popular exchanges. Enable 'Use all ccxt exchanges' only if you understand it will be slow.")
    use_all = st.checkbox("Use ALL exchanges supported by ccxt (~100+)", value=False)
    if not use_all:
        selected_exchanges = st.multiselect("Choose exchanges", options=DEFAULT_EXCHANGES, default=DEFAULT_EXCHANGES)
    else:
        selected_exchanges = st.multiselect("Choose (loaded) exchanges", options=ccxt.exchanges, default=list(ccxt.exchanges)[:80])

    st.markdown("---")
    st.subheader("Fees & alert")
    taker_fee_percent = st.number_input("Taker fee (%) to estimate (per exchange)", min_value=0.0, max_value=5.0, value=0.1, step=0.01)
    transfer_fee_usd = st.number_input("Estimated transfer cost (USD)", min_value=0.0, max_value=100.0, value=5.0, step=0.5)
    alert_threshold_percent = st.number_input("Alert threshold (%)", min_value=0.01, max_value=50.0, value=0.5, step=0.01)

    st.markdown("---")
    st.info("Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in Streamlit Secrets (Settings → Secrets) to enable Telegram alerts.")

# --------- Utility functions ----------
def instantiate_exchange(name):
    """Instantiate and cache ccxt exchange instance (lazy)."""
    if name in st.session_state["exchanges_cache"]:
        return st.session_state["exchanges_cache"][name]
    try:
        if not hasattr(ccxt, name):
            return None
        ex_cls = getattr(ccxt, name)
        ex = ex_cls({"enableRateLimit": True, "timeout": 15000})
        st.session_state["exchanges_cache"][name] = ex
        return ex
    except Exception:
        return None

def find_symbol_for_exchange(ex, base):
    """Find a tradable symbol like 'ETH/USDT' on the exchange, trying fallbacks."""
    if ex is None:
        return None
    try:
        # load markets once per exchange per session
        if ex.id not in st.session_state["markets_loaded"]:
            try:
                ex.load_markets()
            except Exception:
                pass
            st.session_state["markets_loaded"].add(ex.id)
        markets = getattr(ex, "markets", None)
        if not markets:
            return None
        for q in QUOTE_PREFERENCES:
            s = f"{base}/{q}"
            if s in ex.symbols:
                return s
        # best effort: return any symbol that starts with base + '/'
        for s in ex.symbols:
            if s.startswith(base + "/"):
                return s
    except Exception:
        return None
    return None

def fetch_ticker_safe(ex, symbol):
    """Fetch ticker with error handling."""
    try:
        ticker = ex.fetch_ticker(symbol)
        # ensure numeric values
        bid = ticker.get("bid")
        ask = ticker.get("ask")
        last = ticker.get("last")
        # If both are None but last exists, use last for both
        if bid is None and last is not None:
            bid = last
        if ask is None and last is not None:
            ask = last
        return {"bid": bid, "ask": ask, "last": last}
    except Exception:
        return None

def get_prices_for_coin(base, exchanges_list):
    """Return dict: exchange -> {symbol, bid, ask, last}"""
    out = {}
    for name in exchanges_list:
        ex = instantiate_exchange(name)
        if ex is None:
            continue
        symbol = find_symbol_for_exchange(ex, base)
        if not symbol:
            continue
        ticker = fetch_ticker_safe(ex, symbol)
        if ticker is None:
            continue
        # only include if we have a numeric bid/ask/last
        if all(v is None for v in (ticker.get("bid"), ticker.get("ask"), ticker.get("last"))):
            continue
        out[name] = {"symbol": symbol, "bid": ticker.get("bid"), "ask": ticker.get("ask"), "last": ticker.get("last")}
    return out

def compute_effective_prices(record, fee_percent):
    """
    Given a record {ask,bid}, compute effective buy (you pay ask+fee) and effective sell (you receive bid-fee).
    """
    ask = record.get("ask")
    bid = record.get("bid")
    if ask is None or bid is None:
        # fallback to last if available
        last = record.get("last")
        if last is None:
            return None, None
        ask = ask or last
        bid = bid or last
    fee_factor_buy = 1 + fee_percent / 100.0  # you pay fee when buying (taker)
    fee_factor_sell = 1 - fee_percent / 100.0  # you lose fee when selling
    effective_buy = ask * fee_factor_buy
    effective_sell = bid * fee_factor_sell
    return effective_buy, effective_sell

def send_telegram(message):
    """Send Telegram message if credentials present."""
    token = TELEGRAM_BOT_TOKEN
    chat_id = TELEGRAM_CHAT_ID
    if not token or not chat_id:
        return False, "No Telegram configured"
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
        r = requests.post(url, json=payload, timeout=10)
        return (r.status_code == 200), r.text
    except Exception as e:
        return False, str(e)

def append_history_row(row: dict):
    """Append a row to CSV history, create file with header if missing."""
    header = ["timestamp", "coin", "buy_exchange", "buy_symbol", "buy_price", "sell_exchange", "sell_symbol", "sell_price", "profit_usd", "profit_percent"]
    exists = HISTORY_FILE.exists()
    df_row = pd.DataFrame([row])
    if not exists:
        df_row.to_csv(HISTORY_FILE, index=False, columns=header)
    else:
        df_row.to_csv(HISTORY_FILE, index=False, header=False, mode="a", columns=header)

# --------- Main UI / Logic ----------
cols = st.columns([3, 1])
with cols[1]:
    st.markdown("### Controls")
    st.write(f"Selected coin: **{coin}**")
    st.write(f"Exchanges: {len(selected_exchanges)} selected")
    if st.button("Show selected exchanges list"):
        st.write(selected_exchanges)

# fetch & show prices
status = st.empty()
table_area = st.empty()

# If auto refresh requested, implement simple loop using rerun
if auto_refresh:
    # set a small session key to allow periodic reruns
    last_run_key = f"last_run_{coin}"
    now = time.time()
    last_run = st.session_state.get(last_run_key, 0)
    if now - last_run > refresh_interval or ask_refresh:
        st.session_state[last_run_key] = now
    else:
        # if not time yet, show countdown
        remaining = int(max(0, refresh_interval - (now - last_run)))
        st.info(f"Auto-refresh in {remaining}s — click 'Refresh Now' to force.")
        # Do not skip fetching entirely — we still want at least one fetch on first load
        # fall through to normal fetch

# perform a single fetch
with st.spinner("Fetching market data (may take a few seconds for many exchanges)..."):
    prices_raw = get_prices_for_coin(coin, selected_exchanges)

if not prices_raw:
    status.warning("No price data available for selected exchanges/pair. Try a different coin or enable fewer exchanges.")
    st.stop()

# Build DataFrame for display
rows = []
for ex_name, rec in prices_raw.items():
    effective_buy, effective_sell = compute_effective_prices(rec, taker_fee_percent)
    rows.append({
        "exchange": ex_name,
        "symbol": rec.get("symbol"),
        "ask": rec.get("ask"),
        "bid": rec.get("bid"),
        "last": rec.get("last"),
        "effective_buy": effective_buy,
        "effective_sell": effective_sell
    })

df = pd.DataFrame(rows)
# show dataframe (use_container_width for compatibility)
table_area.dataframe(df.sort_values("effective_buy").reset_index(drop=True), use_container_width=True)

# Find best buy (min effective_buy) and best sell (max effective_sell)
df_valid = df.dropna(subset=["effective_buy", "effective_sell"])
if df_valid.empty:
    status.info("Not enough numeric bid/ask data to compute opportunities.")
    st.stop()

best_buy_row = df_valid.loc[df_valid["effective_buy"].idxmin()]
best_sell_row = df_valid.loc[df_valid["effective_sell"].idxmax()]

profit_usd = best_sell_row["effective_sell"] - best_buy_row["effective_buy"] - transfer_fee_usd
profit_percent = (profit_usd / best_buy_row["effective_buy"]) * 100 if best_buy_row["effective_buy"] and best_sell_row["effective_sell"] else 0.0

st.markdown("---")
st.subheader("Best Current Opportunity (after fees & transfer cost)")
st.write(f"Buy on **{best_buy_row['exchange']}** ({best_buy_row['symbol']}) at **{best_buy_row['effective_buy']:.6f}** USD")
st.write(f"Sell on **{best_sell_row['exchange']}** ({best_sell_row['symbol']}) at **{best_sell_row['effective_sell']:.6f}** USD")
st.write(f"Estimated net profit per unit: **{profit_usd:.6f} USD**")
st.write(f"Estimated profit percentage: **{profit_percent:.4f}%**")

# Alert logic
alert_key = f"{coin}_{best_buy_row['exchange']}_{best_sell_row['exchange']}_{int(best_buy_row['effective_buy'] or 0)}_{int(best_sell_row['effective_sell'] or 0)}"
if profit_percent > alert_threshold_percent:
    if st.session_state["last_alerts"].get(alert_key) is None:
        # Compose Telegram-friendly message
        message = (f"*Arbitrage Alert — {coin}*\n"
                   f"Buy on: *{best_buy_row['exchange']}* ({best_buy_row['symbol']}) at `${best_buy_row['effective_buy']:.6f}`\n"
                   f"Sell on: *{best_sell_row['exchange']}* ({best_sell_row['symbol']}) at `${best_sell_row['effective_sell']:.6f}`\n"
                   f"Net profit: `${profit_usd:.6f}` ({profit_percent:.4f}%)\n"
                   f"Timestamp: {datetime.utcnow().isoformat()} UTC")
        ok, info = send_telegram(message)
        if ok:
            status.success("Telegram alert sent ✅")
        else:
            status.warning(f"Telegram alert failed or not configured: {info}")
        # Save to history CSV
        row = {
            "timestamp": datetime.utcnow().isoformat(),
            "coin": coin,
            "buy_exchange": best_buy_row["exchange"],
            "buy_symbol": best_buy_row["symbol"],
            "buy_price": float(best_buy_row["effective_buy"] or 0.0),
            "sell_exchange": best_sell_row["exchange"],
            "sell_symbol": best_sell_row["symbol"],
            "sell_price": float(best_sell_row["effective_sell"] or 0.0),
            "profit_usd": float(profit_usd),
            "profit_percent": float(profit_percent)
        }
        try:
            append_history_row(row)
        except Exception as e:
            st.warning(f"Failed to append history: {e}")
        st.session_state["last_alerts"][alert_key] = datetime.utcnow().isoformat()
    else:
        status.info("Opportunity detected but already alerted recently (dedup).")
else:
    status.info("No alert — profit below threshold.")

# History view & download
st.markdown("---")
st.subheader("History & Downloads")
if HISTORY_FILE.exists():
    try:
        hist_df = pd.read_csv(HISTORY_FILE, parse_dates=["timestamp"])
        st.write(f"Total logged alerts: {len(hist_df)}")
        st.dataframe(hist_df.sort_values("timestamp", ascending=False).head(50), use_container_width=True)
        csv_bytes = hist_df.to_csv(index=False).encode("utf-8")
        st.download_button("Download Full History CSV", csv_bytes, file_name="arbitrage_history.csv", mime="text/csv")
    except Exception as e:
        st.warning(f"Could not read history file: {e}")
else:
    st.info("No history yet. Alerts will be logged here when profit threshold is met.")

# Footer
st.markdown("---")
st.caption("Notes: Querying many exchanges may be slow or partially blocked on free hosting. Use a small selection for faster results. There are not 1000 direct exchange APIs available in ccxt — ccxt supports ~100-150 exchanges. For real trading you must account for liquidity, withdrawal times, and KYC/API keys.")
