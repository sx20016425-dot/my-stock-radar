import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import time
import random
import datetime

st.set_page_config(page_title="Alpha Trader v21 CONTROL DECK", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# =========================
# STATE (完全保留 v20)
# =========================
for k in ["last_book", "alerts", "trades", "signals", "flow_state"]:
    if k not in st.session_state:
        st.session_state[k] = {} if k == "flow_state" else [] if k != "last_book" else None

# =========================
# FORMAT
# =========================
def f2(x):
    try:
        return "--" if x is None else f"{float(x):.2f}"
    except:
        return "--"

# =========================
# 🌍 GLOBAL MARKET (TOP BAR)
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
# STOCK ENGINE
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
        "bids": [{"price": p-i*0.5, "size": random.randint(10,120)} for i in range(5)],
        "asks": [{"price": p+i*0.5, "size": random.randint(10,120)} for i in range(5)],
        "lastPrice": p,
        "lastSize": random.randint(1,80)
    }, "SIM"

# =========================
# BOOK
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
# DELTA ENGINE
# =========================
def delta(curr, prev):
    if not prev:
        return pd.DataFrame()

    rows = []
    for i in range(2):
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
# FLOW ENGINE (保留)
# =========================
def flow(curr, prev):
    out = []
    if not prev:
        return out

    for i in range(2):
        cb = curr["bids"][i]
        pb = prev["bids"][i]
        ca = curr["asks"][i]
        pa = prev["asks"][i]

        if cb["size"] > pb["size"]*1.5:
            out.append("🟢 買單加壓")

        if ca["size"] > pa["size"]*1.5:
            out.append("🔴 賣壓加單")

        if cb["size"] < pb["size"]*0.5:
            out.append("⚪ 買單抽離")

        if ca["size"] < pa["size"]*0.5:
            out.append("⚪ 賣單撤單")

    return out

# =========================
# UI HEADER (移除標題 ✔)
# =========================

symbol = st.text_input("股票代碼", "2330")

# =========================
# 🌍 TOP GLOBAL MARKET (縮小 + 最上)
# =========================
g = fetch_global()

top_cols = st.columns(4)

for i,(k,v) in enumerate(g.items()):
    p,pct = v
    with top_cols[i]:
        st.metric(k, f2(p), f"{pct:.2f}%")

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

# =========================
# LAYOUT CORE (你的要求重排)
# =========================
left, right = st.columns([1, 2])

# =========================
# LEFT COLUMN
# =========================
with left:

    st.subheader("📊 五檔（盤口）")
    st.dataframe(safe_book(bids,asks), use_container_width=True)

# =========================
# RIGHT COLUMN SPLIT
# =========================
right_top, right_bottom = st.columns([1,1])

# =========================
# RIGHT TOP (DELTA)
# =========================
with right_top:

    st.subheader("📈 掛單變化（Delta）")
    st.dataframe(delta(snap, st.session_state.last_book), use_container_width=True)

# =========================
# RIGHT BOTTOM (CONTROL WALL)
# =========================
with right_bottom:

    st.subheader("🧠 監控狀態牆")

    flow_data = flow(snap, st.session_state.last_book)

    for f in flow_data:
        st.session_state.alerts.insert(0, f)

    st.code("\n".join(st.session_state.alerts[:25]) or "無")

    st.divider()

    st.metric("成交價", f2(lp))
    st.metric("成交量", lv)
    st.metric("模式", mode)

# =========================
# SAVE STATE
# =========================
st.session_state.last_book = snap

# =========================
# LOOP
# =========================
time.sleep(2)
st.rerun()
