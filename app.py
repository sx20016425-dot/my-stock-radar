import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import time
import random
import datetime

st.set_page_config(page_title="Alpha-Trader v18 FULL CORE", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# =========================
# INIT
# =========================
for k, v in {
    "last_book": None,
    "alerts": [],
    "trades": [],
    "signals": []
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# =========================
# FORMAT
# =========================
def f2(x):
    try:
        return "--" if x is None else f"{float(x):.2f}"
    except:
        return "--"

# =========================
# 🌍 GLOBAL INDEX (RESTORED)
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
            if df is None or df.empty:
                raise Exception("no data")

            p = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2]) if len(df) > 1 else p
            pct = (p - prev) / prev * 100

            out[k] = (p, pct)
        except:
            out[k] = (None, None)

    return out

# =========================
# STOCK DATA
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
# SAFE BOOK (FIXED)
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
# ENGINE
# =========================
def imbalance(b, a):
    try:
        return (sum(b.values()) - sum(a.values())) / (sum(b.values()) + sum(a.values()) + 1)
    except:
        return 0

def signal_engine(score, imb, lv):
    sig = []

    if score > 65 and imb > 0.2:
        sig.append(("LONG", "多單進場"))

    if score < 35 and imb < -0.2:
        sig.append(("SHORT", "空單進場"))

    if lv and lv > 40 and score > 60:
        sig.append(("BREAK", "突破"))

    if lv and lv > 40 and score < 40:
        sig.append(("FAKE", "假突破"))

    return sig

def action(sig, lp):
    if sig == "LONG":
        return f"🟢 做多 @ {f2(lp)}"
    if sig == "SHORT":
        return f"🔴 做空 @ {f2(lp)}"
    if sig == "BREAK":
        return f"🚀 追突破 @ {f2(lp)}"
    if sig == "FAKE":
        return f"⚠️ 假突破 @ {f2(lp)}"
    return None

# =========================
# UI
# =========================
st.title("🏛️ Alpha-Trader v18 FULL SYSTEM")

symbol = st.text_input("股票代碼", "2330")

# =========================
# 🌍 GLOBAL PANEL (RESTORED)
# =========================
st.subheader("🌍 全球市場")

global_data = fetch_global()
cols = st.columns(4)

for i, (k, v) in enumerate(global_data.items()):
    p, pct = v
    cols[i].metric(k, f2(p), f"{pct:.2f}%" if pct else "--")

st.divider()

# =========================
# STOCK
# =========================
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
# SCORE
# =========================
imb = imbalance(curr_b, curr_a)
score = 50 + imb * 100

# =========================
# SIGNALS
# =========================
signals = signal_engine(score, imb, lv)

for s in signals:
    st.session_state.signals.insert(0, s[1])
    act = action(s[0], lp)
    if act:
        st.session_state.trades.insert(0, act)

# =========================
# BOOK
# =========================
st.subheader("📊 五檔")
st.dataframe(safe_book(bids, asks), use_container_width=True)

# =========================
# DASHBOARD
# =========================
c1, c2, c3 = st.columns(3)

with c1:
    st.metric("多空強度", f"{score:.1f}")

with c2:
    st.metric("市場失衡", f"{imb:.3f}")

with c3:
    st.metric("成交價", f2(lp))

# =========================
# OUTPUT
# =========================
col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("🚨 訊號")
    st.code("\n".join([str(x) for x in st.session_state.signals[:20]]) or "無")

with col2:
    st.subheader("📜 交易決策")
    st.code("\n".join([str(x) for x in st.session_state.trades[:20]]) or "無")

with col3:
    st.subheader("⚠️ 警報")
    st.code("\n".join([str(x) for x in st.session_state.alerts[:20]]) or "無")

# =========================
# UPDATE
# =========================
st.session_state.trades.insert(0, f"{f2(lp)} | {lv}")

time.sleep(2)
st.rerun()
