import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import random
import time

st.set_page_config(page_title="Alpha-Trader v28 FIXED", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# =========================
# 🧠 STATE SAFE
# =========================
for k in ["book", "alerts"]:
    if k not in st.session_state:
        st.session_state[k] = []

# =========================
# SAFE FORMAT
# =========================
def f(x):
    try:
        return "--" if x is None else f"{float(x):.2f}"
    except:
        return "--"

# =========================
# 🌍 GLOBAL (NEVER REMOVE)
# =========================
def global_market():
    idx = {
        "S&P500": "^GSPC",
        "NASDAQ": "^IXIC",
        "日經": "^N225",
        "恆生": "^HSI",
        "韓國": "^KS11"
    }

    out = {}
    for k, v in idx.items():
        try:
            df = yf.Ticker(v).history(period="2d")
            p = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2])
            out[k] = (p, (p - prev) / prev * 100)
        except:
            out[k] = (None, None)

    return out

# =========================
# STOCK ENGINE
# =========================
def fetch(symbol):
    try:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
        r = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)

        if r.status_code == 200:
            d = r.json()
            if d.get("bids") and d.get("asks"):
                return d, "LIVE"
    except:
        pass

    # fallback SIM (NO LOSS)
    df = yf.Ticker(f"{symbol}.TW").history(period="1d")
    if df is None or df.empty:
        return {
            "bids": [],
            "asks": [],
            "lastPrice": None,
            "lastSize": None
        }, "FAIL"

    p = float(df["Close"].iloc[-1])

    return {
        "bids": [{"price": p-i*0.5, "size": random.randint(10,80)} for i in range(5)],
        "asks": [{"price": p+i*0.5, "size": random.randint(10,80)} for i in range(5)],
        "lastPrice": p,
        "lastSize": random.randint(1,50)
    }, "SIM"

# =========================
# SAFE TABLE
# =========================
def book(bids, asks):
    try:
        n = 5
        bids = (bids or []) + [{} for _ in range(n - len(bids or []))]
        asks = (asks or []) + [{} for _ in range(n - len(asks or []))]

        return pd.DataFrame({
            "買價": [x.get("price") for x in bids],
            "買量": [x.get("size") for x in bids],
            "賣價": [x.get("price") for x in asks],
            "賣量": [x.get("size") for x in asks],
        })
    except:
        return pd.DataFrame(columns=["買價","買量","賣價","賣量"])

# =========================
# UI CONTRACT (CORE NEVER DISAPPEARS)
# =========================
st.title("🏛️ v28 FIXED Stable Trading Engine")

symbol = st.text_input("股票代碼", "2330")

snap, mode = fetch(symbol)

bids = snap["bids"]
asks = snap["asks"]

lp = snap.get("lastPrice")
lv = snap.get("lastSize")

# =========================
# 🌍 GLOBAL (MUST ALWAYS SHOW)
# =========================
st.subheader("🌍 全球市場")

g = global_market()
cols = st.columns(len(g))

for i, (k, v) in enumerate(g.items()):
    p, pct = v
    cols[i].metric(k, f(p), f"{pct:.2f}%" if pct else "--")

st.divider()

# =========================
# 📊 ORDERBOOK (MUST ALWAYS SHOW)
# =========================
st.subheader("📊 五檔")

st.dataframe(book(bids, asks), use_container_width=True)

# =========================
# 📡 PRICE (MUST ALWAYS SHOW)
# =========================
st.subheader("📡 即時成交")

st.metric("成交價", f(lp))
st.metric("成交量", lv)

# =========================
# 🚨 STATUS (MUST ALWAYS SHOW)
# =========================
st.subheader("🚨 系統狀態")
st.write(mode)

# =========================
# LOOP SAFE
# =========================
time.sleep(2)
st.rerun()
