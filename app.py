import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import time
import random
import datetime

st.set_page_config(page_title="Alpha-Trader v20 INSTITUTIONAL FLOW", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# =========================
# STATE (完全保留 + 擴充)
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
# 🌍 GLOBAL MARKET (保留)
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
# STOCK ENGINE (保留)
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
# BOOK (保留)
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
# 📈 DELTA (保留 + 強化)
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
# 🧠 INSTITUTIONAL FLOW ENGINE（新增核心）
# =========================
def institutional_flow(curr, prev):
    signals = []

    if not prev:
        return signals

    try:
        for i in range(2):

            cb = curr["bids"][i]
            pb = prev["bids"][i]

            ca = curr["asks"][i]
            pa = prev["asks"][i]

            # =========================
            # 🧲 1. 主力吸籌
            # =========================
            if cb["size"] > pb["size"] * 2:
                signals.append("🟢 主力吸籌（買單堆積）")

            # =========================
            # 🔴 出貨壓盤
            # =========================
            if ca["size"] > pa["size"] * 2:
                signals.append("🔴 主力壓盤（賣單堆積）")

            # =========================
            # ⚡ 3. 快速抽單（假盤）
            # =========================
            if cb["size"] < pb["size"] * 0.4:
                signals.append("⚠️ 買單抽離（假跌破）")

            if ca["size"] < pa["size"] * 0.4:
                signals.append("⚠️ 賣單撤單（假突破）")

        # =========================
        # ⚡ 4. 成交攻擊力
        # =========================
        spread = curr["lastPrice"]

        bid1 = curr["bids"][0]["size"]
        ask1 = curr["asks"][0]["size"]

        if bid1 > ask1 * 1.8:
            signals.append("🚀 買方攻擊力強")

        if ask1 > bid1 * 1.8:
            signals.append("📉 賣方攻擊力強")

    except:
        pass

    return signals

# =========================
# UI
# =========================
st.title("🏛️ Alpha-Trader v20 INSTITUTIONAL ORDER FLOW")

symbol = st.text_input("股票代碼", "2330")

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

# =========================
# BOOK
# =========================
st.subheader("📊 五檔（完整盤口）")
st.dataframe(safe_book(bids,asks), use_container_width=True)

# =========================
# DELTA
# =========================
st.subheader("📈 掛單變化（Delta）")
st.dataframe(delta(snap, st.session_state.last_book), use_container_width=True)

# =========================
# INSTITUTIONAL FLOW
# =========================
flow = institutional_flow(snap, st.session_state.last_book)

for f in flow:
    st.session_state.alerts.insert(0, f)

st.session_state.last_book = snap

# =========================
# METRICS
# =========================
c1,c2,c3 = st.columns(3)

with c1:
    st.metric("成交價", f2(lp))

with c2:
    st.metric("成交量", lv)

with c3:
    st.metric("模式", mode)

# =========================
# SIGNAL BOARD
# =========================
st.subheader("🚨 機構級籌碼訊號")

st.code("\n".join(st.session_state.alerts[:40]) or "無訊號")

# =========================
# LOOP
# =========================
time.sleep(2)
st.rerun()
