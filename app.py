import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import time
import random
import datetime

st.set_page_config(page_title="Alpha-Trader v18 Execution Core", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# =========================
# INIT
# =========================
for k, v in {
    "last_book": None,
    "alerts": [],
    "trades": [],
    "signals": [],
}.items():
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
# DATA LAYER
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
# SAFE BOOK
# =========================
def safe_book(bids, asks):
    try:
        n = max(len(bids), len(asks), 1)
        bids = bids + [{} for _ in range(n - len(bids))]
        asks = asks + [{} for _ in range(n - len(asks))]

        return pd.DataFrame({
            "買價": [x.get("price") for x in bids],
            "買量": [x.get("size") for x in bids],
            "賣價": [x.get("price") for x in asks],
            "賣量": [x.get("size") for x in asks],
        })
    except:
        return pd.DataFrame()

# =========================
# MICROSTRUCTURE ENGINE
# =========================
def imbalance(bids, asks):
    try:
        b = sum(bids.values())
        a = sum(asks.values())
        return (b - a) / (b + a + 1)
    except:
        return 0

def liquidity_shock(curr, prev):
    if not prev:
        return []

    out = []
    for p, s in curr.items():
        old = prev.get(p, 0)
        diff = s - old

        if diff > 40:
            out.append(("STACK", p, diff))
        elif diff < -40:
            out.append(("PULL", p, diff))
    return out

# =========================
# TRADING MODEL (v18 CORE)
# =========================
def generate_trade_signal(score, lp, lv, imbalance_score):
    signals = []

    # momentum entry
    if score > 65 and imbalance_score > 0.2:
        signals.append(("LONG_ENTRY", "多方進場"))

    if score < 35 and imbalance_score < -0.2:
        signals.append(("SHORT_ENTRY", "空方進場"))

    # breakout / fakeout
    if lv and lv > 40 and score > 60:
        signals.append(("BREAKOUT", "放量突破"))

    if lv and lv > 40 and score < 40:
        signals.append(("FAKEOUT", "假突破警示"))

    return signals

def position_logic(signal, lp):
    if signal == "LONG_ENTRY":
        return f"🟢 做多進場 @ {f2(lp)}"
    if signal == "SHORT_ENTRY":
        return f"🔴 做空進場 @ {f2(lp)}"
    if signal == "BREAKOUT":
        return f"🚀 突破追價 @ {f2(lp)}"
    if signal == "FAKEOUT":
        return f"⚠️ 假突破撤退 @ {f2(lp)}"
    return None

# =========================
# UI
# =========================
st.title("🏛️ Alpha-Trader v18 Trading Decision System")

symbol = st.text_input("股票代碼", "2330")

snap, mode = fetch_stock(symbol)

if not snap:
    st.error("無資料")
    st.stop()

bids = snap["bids"]
asks = snap["asks"]

curr_b = {x.get("price"): x.get("size") for x in bids if x}
curr_a = {x.get("price"): x.get("size") for x in asks if x}

# =========================
# PRICE + FLOW
# =========================
lp = snap.get("lastPrice")
lv = snap.get("lastSize")

imb = imbalance(curr_b, curr_a)

score = 50 + imb * 100

# =========================
# SIGNAL ENGINE
# =========================
signals = generate_trade_signal(score, lp, lv, imb)

for s in signals:
    st.session_state.signals.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {s[1]}")

    trade = position_logic(s[0], lp)
    if trade:
        st.session_state.trades.insert(0, trade)

# =========================
# LIQUIDITY SHOCK
# =========================
shock = liquidity_shock(
    curr_a,
    st.session_state.last_book["a"] if st.session_state.last_book else {}
)

for s in shock:
    typ, p, d = s
    if typ == "PULL":
        st.session_state.alerts.insert(0, f"⚠️ 抽單 {f2(p)} {d}")
    else:
        st.session_state.alerts.insert(0, f"🟢 掛單 {f2(p)} +{d}")

# =========================
# UPDATE BOOK
# =========================
st.session_state.last_book = {"b": curr_b, "a": curr_a}

# =========================
# DASHBOARD
# =========================
c1, c2, c3 = st.columns(3)

with c1:
    st.metric("多空強度", f"{score:.1f}")

with c2:
    st.metric("買賣失衡", f"{imb:.3f}")

with c3:
    st.metric("成交價", f2(lp))

# =========================
# ORDER BOOK
# =========================
st.subheader("📊 五檔")
st.dataframe(safe_book(bids, asks), use_container_width=True)

# =========================
# SIGNALS
# =========================
col1, col2, col3 = st.columns(3)

with col1:
    st.subheader("🚨 主力訊號")
    st.code("\n".join([str(x) for x in st.session_state.signals[:20]]) or "無")

with col2:
    st.subheader("📜 交易決策")
    st.code("\n".join([str(x) for x in st.session_state.trades[:20]]) or "無")

with col3:
    st.subheader("⚠️ 流動性警報")
    st.code("\n".join([str(x) for x in st.session_state.alerts[:20]]) or "無")

# =========================
# LIVE TICK LOG
# =========================
st.session_state.trades.insert(0, f"{f2(lp)} | {lv}")

time.sleep(2)
st.rerun()
