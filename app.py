import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import time
import random

# =========================
# 🏛️ APP
# =========================
st.set_page_config(page_title="Alpha Trader v29 STRUCTURED", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# =========================
# 🧠 STATE
# =========================
if "book" not in st.session_state:
    st.session_state.book = None
if "alerts" not in st.session_state:
    st.session_state.alerts = []
if "trades" not in st.session_state:
    st.session_state.trades = []

# =========================
# SAFE FORMAT
# =========================
def fmt(x):
    try:
        return "--" if x is None else f"{float(x):.2f}"
    except:
        return "--"

# =========================
# 🌍 GLOBAL MODULE (INDEPENDENT)
# =========================
def module_global():
    import yfinance as yf

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
                out[k] = (None, None)
                continue

            p = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2])

            out[k] = (p, (p-prev)/prev*100)

        except:
            out[k] = (None, None)

    return out

# =========================
# 📊 MARKET MODULE (INDEPENDENT)
# =========================
def module_stock(symbol):
    try:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
        r = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)

        if r.status_code == 200:
            d = r.json()
            if d.get("bids") and d.get("asks"):
                return d, "LIVE"
    except:
        pass

    # fallback
    try:
        df = yf.Ticker(f"{symbol}.TW").history(period="1d")
        if df is None or df.empty:
            raise Exception()

        p = float(df["Close"].iloc[-1])

        return {
            "bids": [{"price": p-i*0.5, "size": random.randint(10,80)} for i in range(5)],
            "asks": [{"price": p+i*0.5, "size": random.randint(10,80)} for i in range(5)],
            "lastPrice": p,
            "lastSize": random.randint(1,50)
        }, "SIM"

    except:
        return None, "FAIL"

# =========================
# 📊 ORDER FLOW MODULE (CORE)
# =========================
def module_orderflow(curr, prev):
    alerts = []

    if not curr or not prev:
        return alerts

    try:
        for i in range(2):
            cb = curr["bids"][i]
            pb = prev["bids"][i]

            ca = curr["asks"][i]
            pa = prev["asks"][i]

            if cb["size"] > pb["size"] * 1.5:
                alerts.append(f"🟢 買單加壓 {cb['price']:.2f}")

            if ca["size"] > pa["size"] * 1.5:
                alerts.append(f"🔴 賣壓加單 {ca['price']:.2f}")

    except:
        pass

    return alerts

# =========================
# UI
# =========================
st.title("🏛️ Alpha Trader v29 STRUCTURED ENGINE")

symbol = st.text_input("股票代碼", "2330")

# =========================
# 🌍 GLOBAL (FULL)
# =========================
st.subheader("🌍 全球市場")

g = module_global()
cols = st.columns(len(g))

for i, (k, v) in enumerate(g.items()):
    p, pct = v
    cols[i].metric(k, fmt(p), f"{pct:.2f}%" if pct else "--")

st.divider()

# =========================
# 📊 STOCK
# =========================
snap, mode = module_stock(symbol)

if snap is None:
    st.warning("無法取得股票資料")
    st.stop()

bids = snap["bids"]
asks = snap["asks"]

lp = snap.get("lastPrice")
lv = snap.get("lastSize")

st.subheader("📊 五檔")

df = pd.DataFrame({
    "買價": [x.get("price") for x in bids],
    "買量": [x.get("size") for x in bids],
    "賣價": [x.get("price") for x in asks],
    "賣量": [x.get("size") for x in asks],
})

st.dataframe(df, use_container_width=True)

# =========================
# 📡 TRADE
# =========================
st.subheader("📡 成交")

st.metric("成交價", fmt(lp))
st.metric("成交量", lv)
st.metric("模式", mode)

# =========================
# 🧠 ORDER FLOW
# =========================
curr = snap
prev = st.session_state.book

alerts = module_orderflow(curr, prev)

for a in alerts:
    st.session_state.alerts.insert(0, a)

st.session_state.book = curr

# =========================
# 🚨 ALERTS
# =========================
st.subheader("🚨 Order Flow")

st.code("\n".join(st.session_state.alerts[:20]) or "無")

# =========================
# LOOP
# =========================
time.sleep(2)
st.rerun()
