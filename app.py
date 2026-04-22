import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import numpy as np
import random
import time
import datetime

st.set_page_config(page_title="Alpha-Trader v21 Terminal", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# =========================
# INIT SAFE STATE
# =========================
defaults = {
    "book": None,
    "alerts": [],
    "trades": [],
    "signals": [],
    "pnl": []
}

for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# =========================
# SAFE FORMAT
# =========================
def f2(x):
    try:
        return "--" if x is None else f"{float(x):.2f}"
    except:
        return "--"

# =========================
# =========================
# 🌍 LAYER 1 GLOBAL MARKET
# =========================
@st.cache_data(ttl=5)
def global_market():
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
            pct = (p - prev) / prev * 100
            out[k] = (p, pct)
        except:
            out[k] = (None, None)

    return out

# =========================
# LAYER 2 MARKET DATA
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

    bids = [{"price": p - i*0.5, "size": random.randint(10,80)} for i in range(5)]
    asks = [{"price": p + i*0.5, "size": random.randint(10,80)} for i in range(5)]

    return {
        "bids": bids,
        "asks": asks,
        "lastPrice": p,
        "lastSize": random.randint(1,50)
    }, "SIM"

# =========================
# SAFE BOOK
# =========================
def safe_book(bids, asks):
    n = max(len(bids), len(asks), 1)
    bids = bids + [{} for _ in range(n - len(bids))]
    asks = asks + [{} for _ in range(n - len(asks))]

    return pd.DataFrame({
        "買價": [x.get("price") for x in bids],
        "買量": [x.get("size") for x in bids],
        "賣價": [x.get("price") for x in asks],
        "賣量": [x.get("size") for x in asks],
    })

# =========================
# 🧠 LAYER 3: INSTITUTION FLOW
# =========================
def imbalance(b, a):
    try:
        return (sum(b.values()) - sum(a.values())) / (sum(b.values()) + sum(a.values()) + 1)
    except:
        return 0

def sweep(curr, prev):
    if not prev:
        return []

    out = []
    for p, s in curr.items():
        old = prev.get(p, 0)
        diff = s - old

        if diff > 50:
            out.append(f"🟢 掛單堆積 {f2(p)} +{diff}")
        elif diff < -50:
            out.append(f"🧨 掃單抽撤 {f2(p)} {diff}")
    return out

def inst_score(imb, lv):
    score = 50 + imb * 80
    if lv and lv > 40:
        score += 10
    return max(0, min(100, score))

# =========================
# 📈 LAYER 4 STRATEGY + BACKTEST LIGHT
# =========================
def strategy_signal(score, imb, lv):
    sig = []

    if score > 70 and imb > 0.2:
        sig.append(("LONG", "多單"))

    if score < 30 and imb < -0.2:
        sig.append(("SHORT", "空單"))

    if lv and lv > 50:
        sig.append(("BREAK", "突破"))

    return sig

# =========================
# UI
# =========================
st.title("🏛️ Alpha-Trader v21 ALL-IN-ONE TERMINAL")

symbol = st.text_input("股票代碼", "2330")

snap, mode = fetch_stock(symbol)

if not snap:
    st.error("無資料")
    st.stop()

bids = snap["bids"]
asks = snap["asks"]

curr_b = {x.get("price"): x.get("size") for x in bids if x}
curr_a = {x.get("price"): x.get("size") for x in asks if x}

lp = snap.get("lastPrice")
lv = snap.get("lastSize")

# =========================
# 🌍 GLOBAL LAYER
# =========================
st.subheader("🌍 全球市場")
g = global_market()

cols = st.columns(4)
for i, (k, v) in enumerate(g.items()):
    p, pct = v
    cols[i].metric(k, f2(p), f"{pct:.2f}%" if pct else "--")

st.divider()

# =========================
# 📊 MARKET LAYER
# =========================
st.subheader("📊 五檔")
st.dataframe(safe_book(bids, asks), use_container_width=True)

# =========================
# 🧠 INSTITUTION LAYER
# =========================
imb = imbalance(curr_b, curr_a)
score = inst_score(imb, lv)

sw = sweep(curr_a, st.session_state.book["a"] if st.session_state.book else {})

for s in sw:
    st.session_state.alerts.insert(0, s)

# =========================
# STRATEGY LAYER
# =========================
sig = strategy_signal(score, imb, lv)

for s in sig:
    st.session_state.signals.insert(0, s[1])
    st.session_state.trades.insert(0, f"{s[1]} @ {f2(lp)}")

# =========================
# UPDATE STATE
# =========================
st.session_state.book = {"b": curr_b, "a": curr_a}

# =========================
# DASHBOARD
# =========================
c1, c2, c3 = st.columns(3)

with c1:
    st.metric("機構分數", f"{score:.1f}")

with c2:
    st.metric("市場失衡", f"{imb:.3f}")

with c3:
    st.metric("成交價", f2(lp))

# =========================
# OUTPUT
# =========================
col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("🚨 流動性警報")
    st.code("\n".join(st.session_state.alerts[:20]) or "無")

with col2:
    st.subheader("📊 策略訊號")
    st.code("\n".join(st.session_state.signals[:20]) or "無")

with col3:
    st.subheader("📜 交易決策")
    st.code("\n".join(st.session_state.trades[:20]) or "無")

# =========================
# LOOP
# =========================
st.session_state.trades.insert(0, f"{f2(lp)} | {lv}")

time.sleep(2)
st.rerun()
