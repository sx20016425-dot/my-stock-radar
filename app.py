import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import time
import random

# =========================
# 🏛️ BASIC CONFIG
# =========================
st.set_page_config(page_title="Alpha Trader vFinal Core", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# =========================
# 🧠 STATE INIT
# =========================
if "book" not in st.session_state:
    st.session_state.book = None
if "alerts" not in st.session_state:
    st.session_state.alerts = []

# =========================
# SAFE FORMAT FUNCTION
# =========================
def safe(x):
    try:
        return "--" if x is None else f"{float(x):.2f}"
    except:
        return "--"

# =========================
# 🌍 GLOBAL MARKET MODULE
# =========================
def get_global():
    symbols = {
        "日經": "^N225",
        "恆生": "^HSI",
        "韓國": "^KS11",
        "加權": "^TWII",
        "S&P500": "^GSPC",
        "NASDAQ": "^IXIC"
    }

    result = {}

    for k, v in symbols.items():
        try:
            df = yf.Ticker(v).history(period="2d")

            if df is None or df.empty:
                result[k] = (None, None)
                continue

            now = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2])

            pct = (now - prev) / prev * 100
            result[k] = (now, pct)

        except:
            result[k] = (None, None)

    return result

# =========================
# 📊 STOCK DATA MODULE
# =========================
def get_stock(symbol):
    # 1. Fugle
    try:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
        r = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)

        if r.status_code == 200:
            d = r.json()
            if d.get("bids") and d.get("asks"):
                return d, "LIVE"
    except:
        pass

    # 2. Yahoo fallback
    try:
        df = yf.Ticker(f"{symbol}.TW").history(period="1d")

        if df is None or df.empty:
            raise Exception()

        price = float(df["Close"].iloc[-1])

        return {
            "bids": [{"price": price-i*0.5, "size": random.randint(10,80)} for i in range(5)],
            "asks": [{"price": price+i*0.5, "size": random.randint(10,80)} for i in range(5)],
            "lastPrice": price,
            "lastSize": random.randint(1,50)
        }, "SIM"

    except:
        return {
            "bids": [],
            "asks": [],
            "lastPrice": None,
            "lastSize": None
        }, "FAIL"

# =========================
# 📊 ORDER BOOK VIEW
# =========================
def build_book(bids, asks):
    n = 5

    bids = (bids or []) + [{} for _ in range(n - len(bids or []))]
    asks = (asks or []) + [{} for _ in range(n - len(asks or []))]

    return pd.DataFrame({
        "買價": [x.get("price") for x in bids],
        "買量": [x.get("size") for x in bids],
        "賣價": [x.get("price") for x in asks],
        "賣量": [x.get("size") for x in asks],
    })

# =========================
# 🧠 ORDER FLOW ENGINE
# =========================
def order_flow(curr, prev):
    alerts = []

    if not prev:
        return alerts

    try:
        for i in range(2):
            cb = curr["bids"][i]
            pb = prev["bids"][i]

            ca = curr["asks"][i]
            pa = prev["asks"][i]

            # 🟢 buy strength
            if cb["size"] > pb["size"] * 1.5:
                alerts.append(f"🟢 買單加壓 {cb['price']:.2f}")

            if cb["size"] < pb["size"] * 0.5:
                alerts.append(f"⚪ 買單抽離 {cb['price']:.2f}")

            # 🔴 sell pressure
            if ca["size"] > pa["size"] * 1.5:
                alerts.append(f"🔴 賣壓加單 {ca['price']:.2f}")

            if ca["size"] < pa["size"] * 0.5:
                alerts.append(f"⚪ 賣壓撤單 {ca['price']:.2f}")

    except:
        pass

    return alerts

# =========================
# 🏛️ UI
# =========================
st.title("🏛️ Alpha Trader vFinal Core Engine")

symbol = st.text_input("股票代碼", "2330")

# =========================
# 🌍 GLOBAL PANEL
# =========================
st.subheader("🌍 全球市場")

global_data = get_global()
cols = st.columns(len(global_data))

for i, (k, v) in enumerate(global_data.items()):
    price, pct = v
    cols[i].metric(k, safe(price), f"{pct:.2f}%" if pct else "--")

st.divider()

# =========================
# 📊 STOCK DATA
# =========================
snap, mode = get_stock(symbol)

bids = snap["bids"]
asks = snap["asks"]

lp = snap.get("lastPrice")
lv = snap.get("lastSize")

st.subheader("📊 五檔報價")

st.dataframe(build_book(bids, asks), use_container_width=True)

# =========================
# 📡 TRADE INFO
# =========================
st.subheader("📡 成交資訊")

st.metric("成交價", safe(lp))
st.metric("成交量", lv)
st.metric("資料模式", mode)

# =========================
# 🧠 ORDER FLOW
# =========================
curr = snap
prev = st.session_state.book

alerts = order_flow(curr, prev)

for a in alerts:
    st.session_state.alerts.insert(0, a)

st.session_state.book = curr

# =========================
# 🚨 ALERT PANEL
# =========================
st.subheader("🚨 主力訊號")

st.code("\n".join(st.session_state.alerts[:20]) or "無訊號")

# =========================
# 🔁 LOOP
# =========================
time.sleep(2)
st.rerun()
