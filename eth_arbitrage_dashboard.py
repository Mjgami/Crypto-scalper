Shared streamlit as st import pandas as pd import ccxt import time import requests from datetime import datetime

------------------- CONFIGURATION -------------------

COINS = ["ETH/USDT", "BTC/USDT", "BNB/USDT", "SOL/USDT", "TON/USDT", "ADA/USDT", "DOGE/USDT"] EXCHANGES = [ 'binance', 'coinbasepro', 'kraken', 'kucoin', 'okx', 'gateio', 'bitstamp', 'bybit', 'huobi', 'mexc', 'bitget', 'bitmart', 'lbank', 'whitebit', 'coinex' ]

------------------------------------------------------

def fetch_prices(symbol): prices = {} for name in EXCHANGES: try: exchange = getattr(ccxt, name)() ticker = exchange.fetch_ticker(symbol) prices[name] = ticker['last'] except Exception: continue return prices

def send_telegram_alert(bot_token, chat_id, message): if bot_token and chat_id: url = f"https://api.telegram.org/bot{bot_token}/sendMessage" data = {"chat_id": chat_id, "text": message} try: requests.post(url, data=data) except Exception: pass

def calculate_arbitrage(prices, taker_fee=0.001): if not prices: return None sorted_prices = sorted(prices.items(), key=lambda x: x[1]) buy_exchange, buy_price = sorted_prices[0] sell_exchange, sell_price = sorted_prices[-1] buy_effective = buy_price * (1 + taker_fee) sell_effective = sell_price * (1 - taker_fee) profit = sell_effective - buy_effective profit_percent = (profit / buy_effective) * 100 return { 'buy_exchange': buy_exchange, 'buy_price': buy_price, 'sell_exchange': sell_exchange, 'sell_price': sell_price, 'profit': profit, 'profit_percent': profit_percent }

#Shared area to track last_alerts so we don't spam

if 'last_alert' not in st.session_state: st.session_state['last_alert'] = {}

Streamlit UI

st.set_page_config(page_title="Crypto Arbitrage Dashboard", layout="wide") st.title("💰 Multi-Coin Arbitrage Dashboard")

bot_token = st.secrets.get("TELEGRAM_BOT_TOKEN", "") chat_id = st.secrets.get("TELEGRAM_CHAT_ID", "")

selected_tab = st.sidebar.radio("Select Coin", COINS + ["History"])

if selected_tab == "History": st.header("📜 Arbitrage History") try: history = pd.read_csv("arbitrage_history.csv") st.dataframe(history, use_container_width=True) st.download_button("Download CSV", history.to_csv(index=False), "history.csv") except FileNotFoundError: st.info("No history yet.") else: symbol = selected_tab st.subheader(f"Live Prices for {symbol}")

prices = fetch_prices(symbol)
if prices:
    df = pd.DataFrame(list(prices.items()), columns=['Exchange', 'Price'])
    st.dataframe(df, use_container_width=True)

    result = calculate_arbitrage(prices)
    if result:
        st.metric(label="Best Buy Exchange", value=result['buy_exchange'])
        st.metric(label="Buy Price", value=f"${result['buy_price']:.2f}")
        st.metric(label="Best Sell Exchange", value=result['sell_exchange'])
        st.metric(label="Sell Price", value=f"${result['sell_price']:.2f}")
        st.metric(label="Profit %", value=f"{result['profit_percent']:.2f}%")

        if result['profit_percent'] > 0.5:
            message = (f"🚀 Arbitrage Signal for {symbol}\n"
                       f"Buy on {result['buy_exchange']} at ${result['buy_price']:.2f}\n"
                       f"Sell on {result['sell_exchange']} at ${result['sell_price']:.2f}\n"
                       f"Profit: {result['profit_percent']:.2f}%")
            last_msg = st.session_state['last_alert'].get(symbol, '')
            if message != last_msg:
                send_telegram_alert(bot_token, chat_id, message)
                st.session_state['last_alert'][symbol] = message

                log = pd.DataFrame([{
                    'Time': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                    'Coin': symbol,
                    'Buy Exchange': result['buy_exchange'],
                    'Buy Price': result['buy_price'],
                    'Sell Exchange': result['sell_exchange'],
                    'Sell Price': result['sell_price'],
                    'Profit %': result['profit_percent']
                }])
                try:
                    old = pd.read_csv('arbitrage_history.csv')
                    log = pd.concat([old, log], ignore_index=True)
                except FileNotFoundError:
                    pass
                log.to_csv('arbitrage_history.csv', index=False)

    else:
        st.warning("Not enough data to calculate arbitrage.")
else:
    st.error("Failed to fetch prices from exchanges.")
