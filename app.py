import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import time
import random
import datetime

st.set_page_config(page_title="Alpha-Trader v19 ORDER FLOW", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# =========================
# STATE
# =========================
for k in ["last_book", "alerts", "trades", "signals"]:
    if k not in st.session_state:
        st.session_state[k] = [] if k != "last_book" else None

# =========================
# FORMAT
# =========================
def f2(x):
    try:
        return "--" if x is None else f"{float(x):.2f}"
    except:
        return "--"

# =========================
# 🌍 GLOBAL
# =========================
@st.cache_data(ttl=5)
def fetch_global():
    idx = {
        "日經": "^N225",
        "恆生": "^HSI",
        "韓國": "^KS11",
        "加權": "^TWII"
    }

    out = {}
    for k, v in idx.items():
        try:
            df = yf.Ticker(v).history(period="2d")
            p = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2])
            out[k] = (p, (p-prev)/prev*100)
        except:
            out[k] = (None, None)
    return out

# =========================
# STOCK
# =========================
def fetch_stock(symbol):
    try:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
        r = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)

        if r.status_code == 200:
            d = r.json()
            if d.get("bids") and d.get("asks"):
                return d, "REAL"
    except:
        pass

    df = yf.Ticker(f"{symbol}.TW").history(period="1d")
    if df is None or df.empty:
        return None, "NONE"

    p = float(df["Close"].iloc[-1])

    return {
        "bids": [{"price": p-i*0.5, "size": random.randint(10,80)} for i in range(5)],
        "asks": [{"price": p+i*0.5, "size": random.randint(10,80)} for i in range(5)],
        "lastPrice": p,
        "lastSize": random.randint(1,50)
    }, "SIM"

# =========================
# BOOK SAFE
# =========================
def safe_book(bids, asks):
    bids = bids + [{} for _ in range(5-len(bids))]
    asks = asks + [{} for _ in range(5-len(asks))]

    return pd.DataFrame({
        "買價": [x.get("price") for x in bids],
        "買量": [x.get("size") for x in bids],
        "賣價": [x.get("price") for x in asks],
        "賣量": [x.get("size") for x in asks],
    })

# =========================
# 🧠 DELTA ENGINE (核心補上)
# =========================
def delta(curr, prev):
    if not prev:
        return None

    rows = []
    for i in range(2):  # 交戰區
        cb = curr["bids"][i]
        pb = prev["bids"][i]

        ca = curr["asks"][i]
        pa = prev["asks"][i]

        rows.append([
            cb["price"], cb["size"] - pb["size"],
            ca["price"], ca["size"] - pa["size"]
        ])

    return pd.DataFrame(rows, columns=["買價","買量Δ","賣價","賣量Δ"])

# =========================
# 🧠 ORDER FLOW (升級)
# =========================
def flow(curr, prev):
    alerts = []
    if not prev:
        return alerts

    for i in range(2):
        cb = curr["bids"][i]
        pb = prev["bids"][i]

        ca = curr["asks"][i]
        pa = prev["asks"][i]

        # 加單
        if cb["size"] > pb["size"]*1.5:
            alerts.append(f"🟢 買一加單 {cb['price']:.2f}")

        if ca["size"] > pa["size"]*1.5:
            alerts.append(f"🔴 賣一壓單 {ca['price']:.2f}")

        # 抽單
        if cb["size"] < pb["size"]*0.5:
            alerts.append(f"⚪ 買一抽單 {cb['price']:.2f}")

        if ca["size"] < pa["size"]*0.5:
            alerts.append(f"⚪ 賣一撤單 {ca['price']:.2f}")

    return alerts

# =========================
# UI
# =========================
st.title("🏛️ Alpha Trader v19 ORDER FLOW ENGINE")

symbol = st.text_input("股票", "2330")

# =========================
# GLOBAL
# =========================
g = fetch_global()
cols = st.columns(4)

for i,(k,v) in enumerate(g.items()):
    p,pct = v
    cols[i].metric(k, f2(p), f"{pct:.2f}%")

st.divider()

# =========================
# STOCK
# =========================
snap, mode = fetch_stock(symbol)

if not snap:
    st.error("NO DATA")
    st.stop()

bids = snap["bids"]
asks = snap["asks"]

lp = snap["lastPrice"]
lv = snap["lastSize"]

st.subheader("📊 五檔")
st.dataframe(safe_book(bids,asks), use_container_width=True)

# =========================
# DELTA TABLE（補回核心）
# =========================
st.subheader("📈 掛單變化 (Delta)")

st.dataframe(delta(snap, st.session_state.last_book), use_container_width=True)

# =========================
# FLOW ENGINE
# =========================
alerts = flow(snap, st.session_state.last_book)

for a in alerts:
    st.session_state.alerts.insert(0,a)

st.session_state.last_book = snap

# =========================
# DISPLAY
# =========================
c1,c2,c3 = st.columns(3)

with c1:
    st.metric("成交價", f2(lp))
with c2:
    st.metric("成交量", lv)
with c3:
    st.metric("模式", mode)

st.subheader("🚨 即時盤口訊號")
st.code("\n".join(st.session_state.alerts[:30]) or "無")

# =========================
# LOOP
# =========================
time.sleep(2)
st.rerun()
