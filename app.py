import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import time
import random

# =========================
# 🏛️ APP CONFIG
# =========================
st.set_page_config(page_title="Alpha-Trader v28 SAFE FULL", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# =========================
# 🧠 STATE INIT
# =========================
for k in ["book", "alerts", "trades"]:
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
# 🌍 GLOBAL MARKET (SAFE)
# =========================
def global_market():
    idx = {
        "日經": "^N225",
        "恆生": "^HSI",
        "韓國": "^KS11",
        "加權": "^TWII",
        "S&P500": "^GSPC",
        "NASDAQ": "^IXIC"
    }

    out = {}
    for k, v in idx.items():
        try:
            df = yf.Ticker(v).history(period="2d")

            if df is None or df.empty:
                raise Exception("empty")

            p = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2])

            out[k] = (p, (p - prev) / prev * 100)

        except:
            out[k] = (None, None)

    return out

# =========================
# 📊 STOCK ENGINE (FULL SAFE)
# =========================
def fetch(symbol):
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

    # 2. Yahoo fallback (SAFE FIXED)
    try:
        df = yf.Ticker(f"{symbol}.TW").history(period="1d", timeout=3)

        if df is not None and not df.empty:
            p = float(df["Close"].iloc[-1])

            return {
                "bids": [{"price": p-i*0.5, "size": random.randint(10,80)} for i in range(5)],
                "asks": [{"price": p+i*0.5, "size": random.randint(10,80)} for i in range(5)],
                "lastPrice": p,
                "lastSize": random.randint(1,50)
            }, "SIM"

    except:
        pass

    # 3. HARD FALLBACK (NEVER CRASH)
    return {
        "bids": [{"price": 0, "size": 0} for _ in range(5)],
        "asks": [{"price": 0, "size": 0} for _ in range(5)],
        "lastPrice": None,
        "lastSize": None
    }, "FAIL"

# =========================
# 📊 ORDER BOOK
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

            # buy pressure
            if cb["size"] > pb["size"] * 1.5:
                alerts.append(f"🟢 買單加壓 {cb['price']:.2f}")

            if cb["size"] < pb["size"] * 0.5:
                alerts.append(f"⚪ 買單抽離 {cb['price']:.2f}")

            # sell pressure
            if ca["size"] > pa["size"] * 1.5:
                alerts.append(f"🔴 賣壓加單 {ca['price']:.2f}")

            if ca["size"] < pa["size"] * 0.5:
                alerts.append(f"⚪ 賣壓撤單 {ca['price']:.2f}")

    except:
        pass

    return alerts

# =========================
# UI
# =========================
st.title("🏛️ v28 SAFE FULL ENGINE (No Crash Version)")

symbol = st.text_input("股票代碼", "2330")

snap, mode = fetch(symbol)

bids = snap["bids"]
asks = snap["asks"]

lp = snap.get("lastPrice")
lv = snap.get("lastSize")

# =========================
# 🌍 GLOBAL
# =========================
st.subheader("🌍 全球市場")

g = global_market()
cols = st.columns(len(g))

for i, (k, v) in enumerate(g.items()):
    p, pct = v
    cols[i].metric(k, f(p), f"{pct:.2f}%" if pct else "--")

st.divider()

# =========================
# 📊 ORDER BOOK
# =========================
st.subheader("📊 五檔")

st.dataframe(book(bids, asks), use_container_width=True)

# =========================
# 📡 TRADE
# =========================
st.subheader("📡 即時成交")

st.metric("成交價", f(lp))
st.metric("成交量", lv)
st.metric("資料模式", mode)

# =========================
# 🧠 ORDER FLOW
# =========================
curr = {"bids": bids, "asks": asks}
prev = st.session_state.book

alerts = order_flow(curr, prev)

for a in alerts:
    st.session_state.alerts.insert(0, a)

st.session_state.book = curr

# =========================
# 🚨 ALERTS
# =========================
st.subheader("🚨 Order Flow 警報")

st.code("\n".join(st.session_state.alerts[:20]) or "無")

# =========================
# LOOP SAFE
# =========================
time.sleep(2)
st.rerun()
