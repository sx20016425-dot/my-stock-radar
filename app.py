import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import random
import time

st.set_page_config(page_title="Alpha-Trader v28 ULTRA FIX", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# =========================
# 🧠 STATE (FULL RESTORE)
# =========================
for k in ["book", "alerts", "signals"]:
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
# 🌍 GLOBAL MARKET
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

    # fallback SIM
    df = yf.Ticker(f"{symbol}.TW").history(period="1d")
    p = float(df["Close"].iloc[-1])

    return {
        "bids": [{"price": p-i*0.5, "size": random.randint(10,80)} for i in range(5)],
        "asks": [{"price": p+i*0.5, "size": random.randint(10,80)} for i in range(5)],
        "lastPrice": p,
        "lastSize": random.randint(1,50)
    }, "SIM"

# =========================
# ORDER FLOW ENGINE（你缺的）
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

            # 🟢 買單加單
            if cb["size"] > pb["size"] * 1.5:
                alerts.append(f"🟢 買盤加單 {cb['price']:.2f}")

            # ⚪ 買單抽單
            if cb["size"] < pb["size"] * 0.5:
                alerts.append(f"⚪ 買盤抽單 {cb['price']:.2f}")

            # 🔴 賣壓加單
            if ca["size"] > pa["size"] * 1.5:
                alerts.append(f"🔴 賣壓加單 {ca['price']:.2f}")

            # ⚪ 賣壓抽單
            if ca["size"] < pa["size"] * 0.5:
                alerts.append(f"⚪ 賣壓抽單 {ca['price']:.2f}")

    except:
        pass

    return alerts

# =========================
# SAFE BOOK
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
        return pd.DataFrame()

# =========================
# UI
# =========================
st.title("🏛️ v28 ULTRA FIX FULL ENGINE")

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
# 📊 BOOK
# =========================
st.subheader("📊 五檔")

st.dataframe(book(bids, asks), use_container_width=True)

# =========================
# 🧠 ORDER FLOW（補回來）
# =========================
curr = {"bids": bids, "asks": asks}
prev = st.session_state.book

alerts = order_flow(curr, prev)

for a in alerts:
    st.session_state.alerts.insert(0, a)

st.session_state.book = curr

# =========================
# 📡 TRADE
# =========================
st.subheader("📡 即時成交")

st.metric("成交價", f(lp))
st.metric("成交量", lv)

# =========================
# 🚨 ALERTS（補回來）
# =========================
st.subheader("🚨 Order Flow 警報")

st.code("\n".join(st.session_state.alerts[:20]) or "無")

# =========================
# 🔁 LOOP
# =========================
time.sleep(2)
st.rerun()
