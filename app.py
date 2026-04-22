import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import numpy as np
import random
import time
import datetime

st.set_page_config(page_title="Alpha-Trader v22 Quant Terminal", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# =========================
# 🧠 SAFE STATE (永不覆蓋)
# =========================
def init_state():
    base = {
        "book": None,
        "alerts": [],
        "signals": [],
        "trades": [],
        "metrics": {},
        "errors": []
    }
    for k, v in base.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()

# =========================
# FORMAT SAFE
# =========================
def f2(x):
    try:
        return "--" if x is None else f"{float(x):.2f}"
    except:
        return "--"

# =========================
# 🌍 LAYER 1 GLOBAL MARKET (SAFE)
# =========================
@st.cache_data(ttl=5)
def global_layer():
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
        except Exception as e:
            out[k] = (None, None)
    return out

# =========================
# 📊 LAYER 2 MARKET DATA (SAFE)
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

    # fallback
    try:
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
    except:
        return None, "NONE"

# =========================
# SAFE ORDERBOOK
# =========================
def book(bids, asks):
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

def liquidity_flow(curr, prev):
    if not prev:
        return []

    out = []
    for p, s in curr.items():
        old = prev.get(p, 0)
        diff = s - old

        if diff > 60:
            out.append(f"🟢 堆單 {f2(p)} +{diff}")
        elif diff < -60:
            out.append(f"🧨 抽單 {f2(p)} {diff}")

    return out

def institution_score(imb, lv):
    try:
        score = 50 + imb * 80
        if lv and lv > 40:
            score += 10
        return max(0, min(100, score))
    except:
        return 50

# =========================
# 📈 LAYER 4 STRATEGY ENGINE
# =========================
def strategy(score, imb, lv):
    out = []

    if score > 70 and imb > 0.25:
        out.append(("LONG", "機構多單"))

    if score < 30 and imb < -0.25:
        out.append(("SHORT", "機構空單"))

    if lv and lv > 50:
        out.append(("BREAK", "放量突破"))

    if lv and lv > 50 and abs(imb) < 0.1:
        out.append(("FAKE", "假突破"))

    return out

# =========================
# UI
# =========================
st.title("🏛️ Alpha-Trader v22 Quant Trading Terminal")

symbol = st.text_input("股票代碼", "2330")

snap, mode = fetch_stock(symbol)

if not snap:
    st.error("無資料（API or fallback failed）")
    st.stop()

bids = snap["bids"]
asks = snap["asks"]

curr_b = {x.get("price"): x.get("size") for x in bids if x}
curr_a = {x.get("price"): x.get("size") for x in asks if x}

lp = snap.get("lastPrice")
lv = snap.get("lastSize")

# =========================
# 🌍 GLOBAL LAYER (NO LOSS)
# =========================
st.subheader("🌍 全球市場")

g = global_layer()
cols = st.columns(4)

for i, (k, v) in enumerate(g.items()):
    p, pct = v
    cols[i].metric(k, f2(p), f"{pct:.2f}%" if pct else "--")

st.divider()

# =========================
# 📊 MARKET LAYER
# =========================
st.subheader("📊 五檔深度")
st.dataframe(book(bids, asks), use_container_width=True)

# =========================
# 🧠 INSTITUTION LAYER
# =========================
imb = imbalance(curr_b, curr_a)
score = institution_score(imb, lv)

flow = liquidity_flow(
    curr_a,
    st.session_state.book["a"] if st.session_state.book else {}
)

for f in flow:
    st.session_state.alerts.insert(0, f)

# =========================
# STRATEGY LAYER
# =========================
sig = strategy(score, imb, lv)

for s in sig:
    st.session_state.signals.insert(0, s[1])
    st.session_state.trades.insert(0, f"{s[1]} @ {f2(lp)}")

# =========================
# STATE UPDATE (SAFE)
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
# OUTPUT PANELS (NEVER REMOVE)
# =========================
col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("🚨 流動性行為")
    st.code("\n".join(st.session_state.alerts[:20]) or "無")

with col2:
    st.subheader("📊 訊號系統")
    st.code("\n".join(st.session_state.signals[:20]) or "無")

with col3:
    st.subheader("📜 交易紀錄")
    st.code("\n".join(st.session_state.trades[:20]) or "無")

# =========================
# LOOP SAFE
# =========================
st.session_state.trades.insert(0, f"{f2(lp)} | {lv}")

time.sleep(2)
st.rerun()
