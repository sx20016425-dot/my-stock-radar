import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import numpy as np
import time
import random
import datetime

st.set_page_config(page_title="Alpha-Trader v25 Stable Terminal", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# =========================
# SAFE STATE INIT (NO LOSS)
# =========================
defaults = {
    "book": None,
    "alerts": [],
    "signals": [],
    "trades": [],
    "cache_price": None
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
# 🌍 GLOBAL MARKET SAFE
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
            out[k] = (p, (p - prev) / prev * 100)
        except:
            out[k] = (None, None)

    return out

# =========================
# 📊 SAFE STOCK FETCH
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

    # fallback SIM (never fail)
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
# SAFE BOOK (NO CRASH)
# =========================
def safe_book(bids, asks):
    try:
        n = max(len(bids), len(asks), 5)

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
# 🧠 INSTITUTION CORE
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

        if diff > 60:
            out.append(f"🟢 堆單 {f2(p)} +{diff}")
        elif diff < -60:
            out.append(f"🧨 抽單 {f2(p)} {diff}")

    return out

def score(imb, lv):
    s = 50 + imb * 80
    if lv and lv > 40:
        s += 10
    return max(0, min(100, s))

# =========================
# UI
# =========================
st.title("🏛️ Alpha-Trader v25 Stable Intraday Terminal")

symbol = st.text_input("股票代碼", "2330")

snap, mode = fetch(symbol)

if not snap:
    st.error("系統降級失敗（極少發生）")
    st.stop()

bids = snap["bids"]
asks = snap["asks"]

curr_b = {x.get("price"): x.get("size") for x in bids if x}
curr_a = {x.get("price"): x.get("size") for x in asks if x}

lp = snap.get("lastPrice")
lv = snap.get("lastSize")

# =========================
# 🌍 GLOBAL
# =========================
st.subheader("🌍 全球市場")

g = global_market()
cols = st.columns(4)

for i, (k, v) in enumerate(g.items()):
    p, pct = v
    cols[i].metric(k, f2(p), f"{pct:.2f}%" if pct else "--")

st.divider()

# =========================
# 📊 BOOK
# =========================
st.subheader("📊 五檔")
st.dataframe(safe_book(bids, asks), use_container_width=True)

# =========================
# 🧠 FLOW
# =========================
imb = imbalance(curr_b, curr_a)
s = score(imb, lv)

flow = sweep(curr_a, st.session_state.book["a"] if st.session_state.book else {})

for f in flow:
    st.session_state.alerts.insert(0, f)

# =========================
# SIGNAL
# =========================
if s > 70:
    st.session_state.signals.insert(0, "🟢 多方機構進場")
elif s < 30:
    st.session_state.signals.insert(0, "🔴 空方機構進場")

# =========================
# UPDATE STATE
# =========================
st.session_state.book = {"b": curr_b, "a": curr_a}

# =========================
# DASHBOARD
# =========================
c1, c2, c3 = st.columns(3)

with c1:
    st.metric("機構分數", f"{s:.1f}")

with c2:
    st.metric("市場失衡", f"{imb:.3f}")

with c3:
    st.metric("成交價", f2(lp))

# =========================
# PANELS (NEVER REMOVE)
# =========================
col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("🚨 流動性")
    st.code("\n".join(st.session_state.alerts[:20]) or "無")

with col2:
    st.subheader("📊 訊號")
    st.code("\n".join(st.session_state.signals[:20]) or "無")

with col3:
    st.subheader("📜 狀態")
    st.write(mode)

# =========================
# LOOP SAFE
# =========================
time.sleep(2)
st.rerun()
