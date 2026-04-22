import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import time
import datetime
import random

st.set_page_config(page_title="Alpha-Trader v16 Institutional Lite", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# ======================
# INIT
# ======================
for k, v in {
    "last_book": None,
    "alerts": [],
    "trades": [],
    "pressure": []
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ======================
# FORMAT
# ======================
def f2(x):
    return "--" if x is None else f"{float(x):.2f}"

# ======================
# DATA
# ======================
def fetch_stock(symbol):
    try:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
        r = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)
        if r.status_code == 200:
            d = r.json()
            if d.get("bids") and d.get("asks"):
                return d
    except:
        pass

    # fallback
    try:
        df = yf.Ticker(f"{symbol}.TW").history(period="1d")
        if not df.empty:
            p = float(df["Close"].iloc[-1])

            bids = [{"price": p - i*0.5, "size": random.randint(10,80)} for i in range(5)]
            asks = [{"price": p + i*0.5, "size": random.randint(10,80)} for i in range(5)]

            return {
                "bids": bids,
                "asks": asks,
                "lastPrice": p,
                "lastSize": random.randint(1,50)
            }
    except:
        pass

    return None

# ======================
# MICROSTRUCTURE ENGINE
# ======================

def liquidity_shift(curr, prev):
    if not prev:
        return []

    signals = []

    for p, s in curr.items():
        old = prev.get(p, 0)
        diff = s - old

        if diff < -30:
            signals.append(("PULL", p, diff))
        elif diff > 30:
            signals.append(("STACK", p, diff))

    return signals


def aggression_score(lp, lv, bids, asks):
    bid_sum = sum(bids.values())
    ask_sum = sum(asks.values())

    total = bid_sum + ask_sum + 1

    imbalance = (bid_sum - ask_sum) / total * 100

    if lv > 30:
        imbalance += 10 if lp > max(bids.keys(), default=0) else -10

    return max(0, min(100, 50 + imbalance))


def compression_zone(bids, asks):
    if len(bids) < 2 or len(asks) < 2:
        return False

    bid_spread = max(bids.keys()) - min(bids.keys())
    ask_spread = max(asks.keys()) - min(asks.keys())

    return bid_spread < 1 and ask_spread < 1

# ======================
# UI
# ======================
st.title("🏛️ Alpha-Trader v16 Institutional Lite")

symbol = st.text_input("股票代碼", "2330")

snap = fetch_stock(symbol)

if not snap:
    st.error("無資料")
    st.stop()

bids = snap["bids"]
asks = snap["asks"]

curr_b = {x["price"]: x["size"] for x in bids}
curr_a = {x["price"]: x["size"] for x in asks}

# ======================
# DISPLAY BOOK
# ======================
df = pd.DataFrame(bids).rename(columns={"price":"買價","size":"買量"})
df2 = pd.DataFrame(asks).rename(columns={"price":"賣價","size":"賣量"})

st.dataframe(pd.concat([df, df2], axis=1), use_container_width=True)

# ======================
# MICROSTRUCTURE ANALYSIS
# ======================

lp = snap.get("lastPrice")
lv = snap.get("lastSize")

# 1. 流動性變化
liq_signals = liquidity_shift(curr_a, st.session_state.last_book["a"] if st.session_state.last_book else {})

# 2. 成交推動力
score = aggression_score(lp, lv, curr_b, curr_a)

# 3. 壓縮區
is_compress = compression_zone(curr_b, curr_a)

# ======================
# ALERT ENGINE
# ======================

for s in liq_signals:
    typ, price, diff = s

    if typ == "PULL":
        st.session_state.alerts.insert(0, f"⚠️ 抽單 {f2(price)} -{diff}")
    else:
        st.session_state.alerts.insert(0, f"🟢 掛單 {f2(price)} +{diff}")

if is_compress:
    st.session_state.alerts.insert(0, "📦 價格壓縮區（可能變盤）")

if lp:
    st.session_state.trades.insert(0, f"{f2(lp)} | {lv}")

# ======================
# UPDATE BOOK
# ======================
st.session_state.last_book = {
    "b": curr_b,
    "a": curr_a
}

# ======================
# DASHBOARD
# ======================
col1, col2, col3 = st.columns(3)

with col1:
    st.metric("多空強度", f"{score:.1f} / 100")

with col2:
    st.metric("壓縮狀態", "是" if is_compress else "否")

with col3:
    st.metric("成交價", f2(lp))

st.divider()

# ======================
# OUTPUT
# ======================
c1, c2 = st.columns(2)

with c1:
    st.subheader("🚨 主力行為")
    st.code("\n".join(st.session_state.alerts[:25]) or "無")

with c2:
    st.subheader("📜 成交流")
    st.code("\n".join(st.session_state.trades[:25]) or "無")

time.sleep(2)
st.rerun()
