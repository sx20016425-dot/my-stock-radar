import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import numpy as np
import time
import datetime
import random

st.set_page_config(page_title="Alpha-Trader v26 Global Monitor", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# =========================
# 🧠 SAFE STATE
# =========================
def init():
    keys = {
        "book": None,
        "alerts": [],
        "signals": [],
        "cache": {}
    }
    for k, v in keys.items():
        if k not in st.session_state:
            st.session_state[k] = v

init()

# =========================
# FORMAT SAFE
# =========================
def f2(x):
    try:
        return "--" if x is None else f"{float(x):.2f}"
    except:
        return "--"

# =========================
# 🌍 GLOBAL UNIFIED MARKET LAYER
# =========================
MARKETS = {
    "S&P500": {"type": "y", "sym": "^GSPC"},
    "NASDAQ": {"type": "y", "sym": "^IXIC"},
    "日經": {"type": "y", "sym": "^N225"},
    "韓國": {"type": "y", "sym": "^KS11"},
    "恆生": {"type": "y", "sym": "^HSI"},
    "台指期": {"type": "y", "sym": "^TWII"},  # fallback（若你有Fugle可再升級）
    "台積電ADR": {"type": "y", "sym": "TSM"},
}

def get_market_price(name, cfg):
    try:
        if cfg["type"] == "y":
            df = yf.Ticker(cfg["sym"]).history(period="1d")
            if df is None or df.empty:
                return None, None

            p = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2]) if len(df) > 1 else p
            pct = (p - prev) / prev * 100

            return p, pct

    except:
        pass

    return None, None

# =========================
# 📊 STOCK / FUTURES ENGINE
# =========================
def fetch_stock(symbol):
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
    try:
        df = yf.Ticker(f"{symbol}.TW").history(period="1d")
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
# SAFE BOOK
# =========================
def book(bids, asks):
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
# 🧠 FLOW ENGINE
# =========================
def imbalance(b, a):
    try:
        return (sum(b.values()) - sum(a.values())) / (sum(b.values()) + sum(a.values()) + 1)
    except:
        return 0

def score(imb, lv):
    s = 50 + imb * 80
    if lv and lv > 40:
        s += 10
    return max(0, min(100, s))

# =========================
# UI
# =========================
st.title("🏛️ Alpha-Trader v26 Global Monitoring Terminal")

symbol = st.text_input("台股代碼", "2330")

snap, mode = fetch_stock(symbol)

if not snap:
    st.error("資料失敗")
    st.stop()

bids = snap["bids"]
asks = snap["asks"]

lp = snap.get("lastPrice")
lv = snap.get("lastSize")

curr_b = {x.get("price"): x.get("size") for x in bids if x}
curr_a = {x.get("price"): x.get("size") for x in asks if x}

# =========================
# 🌍 GLOBAL DASHBOARD
# =========================
st.subheader("🌍 全球市場監控")

cols = st.columns(len(MARKETS))

for i, (name, cfg) in enumerate(MARKETS.items()):
    p, pct = get_market_price(name, cfg)
    cols[i].metric(name, f2(p), f"{pct:.2f}%" if pct else "--")

st.divider()

# =========================
# 📊 ORDER BOOK
# =========================
st.subheader("📊 台股五檔")

st.dataframe(book(bids, asks), use_container_width=True)

# =========================
# 🧠 FLOW ANALYSIS
# =========================
imb = imbalance(curr_b, curr_a)
s = score(imb, lv)

# =========================
# SIGNAL ENGINE
# =========================
if s > 70:
    st.session_state.signals.insert(0, "🟢 機構買盤優勢")
elif s < 30:
    st.session_state.signals.insert(0, "🔴 機構賣壓主導")

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
# PANELS (NEVER BREAK)
# =========================
col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("🚨 流動性訊號")
    st.code("\n".join(st.session_state.alerts[:20]) or "無")

with col2:
    st.subheader("📊 策略訊號")
    st.code("\n".join(st.session_state.signals[:20]) or "無")

with col3:
    st.subheader("📡 系統狀態")
    st.write("LIVE / SIM fallback enabled")

# =========================
# LOOP
# =========================
time.sleep(2)
st.rerun()
