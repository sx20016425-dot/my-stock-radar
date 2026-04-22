import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import time
import random

st.set_page_config(page_title="Alpha-Trader v17 Stable Core", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# ======================
# INIT
# ======================
for k, v in {
    "last_book": None,
    "alerts": [],
    "trades": [],
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ======================
# SAFE FORMAT
# ======================
def f2(x):
    try:
        return "--" if x is None else f"{float(x):.2f}"
    except:
        return "--"

# ======================
# SAFE DATA LAYER
# ======================
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

# ======================
# SAFE BOOK (核心修復點)
# ======================
def safe_book(bids, asks):
    try:
        max_len = max(len(bids), len(asks), 1)

        bids = bids + [{} for _ in range(max_len - len(bids))]
        asks = asks + [{} for _ in range(max_len - len(asks))]

        return pd.DataFrame({
            "買價": [x.get("price") for x in bids],
            "買量": [x.get("size") for x in bids],
            "賣價": [x.get("price") for x in asks],
            "賣量": [x.get("size") for x in asks],
        })
    except:
        return pd.DataFrame(columns=["買價","買量","賣價","賣量"])

# ======================
# SIGNAL ENGINE
# ======================
def detect_flow(curr, prev):
    if not prev:
        return []

    signals = []

    for p, s in curr.items():
        old = prev.get(p, 0)
        diff = s - old

        if diff > 30:
            signals.append(f"🟢 掛單增加 {f2(p)} +{diff}")
        elif diff < -30:
            signals.append(f"⚠️ 抽單 {f2(p)} {diff}")

    return signals

def aggression(bids, asks, lp):
    try:
        b = sum(bids.values())
        a = sum(asks.values())
        score = 50 + (b - a) / (b + a + 1) * 50
        return max(0, min(100, score))
    except:
        return 50

# ======================
# UI
# ======================
st.title("🏛️ Alpha-Trader v17 Stable Architecture")

symbol = st.text_input("股票代碼", "2330")

# ======================
# DATA FETCH
# ======================
snap, mode = fetch_stock(symbol)

if not snap:
    st.error("無資料")
    st.stop()

bids = snap["bids"]
asks = snap["asks"]

curr_b = {x.get("price"): x.get("size") for x in bids if x}
curr_a = {x.get("price"): x.get("size") for x in asks if x}

# ======================
# SAFE UI BLOCKS（重點）
# ======================

try:
    st.subheader("📊 五檔")
    book_df = safe_book(bids, asks)
    st.dataframe(book_df, use_container_width=True)
except:
    st.warning("五檔資料異常")

try:
    st.subheader("📈 主力強度")
    lp = snap.get("lastPrice")
    score = aggression(curr_b, curr_a, lp)
    st.metric("多空分數", f"{score:.1f}/100")
except:
    st.warning("分析失敗")

try:
    lp = snap.get("lastPrice")
    lv = snap.get("lastSize")

    if lp:
        st.session_state.trades.insert(0, f"{f2(lp)} | {lv}")

except:
    pass

# ======================
# SAFE OUTPUT
# ======================
col1, col2 = st.columns(2)

with col1:
    st.subheader("🚨 訊號")
    try:
        st.code("\n".join([str(x) for x in st.session_state.alerts[:25]]) or "無")
    except:
        st.code("無")

with col2:
    st.subheader("📜 成交流")
    try:
        st.code("\n".join([str(x) for x in st.session_state.trades[:25]]) or "無")
    except:
        st.code("無")

# ======================
# BOOK UPDATE
# ======================
st.session_state.last_book = {
    "b": curr_b,
    "a": curr_a
}

time.sleep(2)
st.rerun()
