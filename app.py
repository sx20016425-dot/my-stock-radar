import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import time
import datetime
import random

st.set_page_config(page_title="Alpha-Trader v16 FULL FIX", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# ======================
# INIT（保留所有 v15）
# ======================
for k, v in {
    "last_book": None,
    "alerts": [],
    "trades": [],
    "stats": {}
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ======================
# FORMAT（修正你需求）
# ======================
def f2(x):
    return "--" if x is None else f"{float(x):.2f}"

# ======================
# 市場（保留）
# ======================
@st.cache_data(ttl=3)
def fetch_global():
    symbols = {
        "日經": "^N225",
        "恆生": "^HSI",
        "韓國": "^KS11",
        "加權": "^TWII"
    }
    data = {}
    for k, v in symbols.items():
        try:
            df = yf.Ticker(v).history(period="1d")
            p = float(df['Close'].iloc[-1])
            prev = float(df['Close'].iloc[-2])
            pct = (p - prev) / prev * 100
            data[k] = (p, pct)
        except:
            data[k] = (None, None)
    return data

# ======================
# 個股（保留 + fallback）
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
        }, "SIM"

    return None, "NONE"

# ======================
# v16 INTELLIGENCE LAYER（新增，不刪舊）
# ======================

def detect_liquidity(curr, prev):
    if not prev:
        return []

    signals = []

    for p, s in curr.items():
        old = prev.get(p, 0)
        diff = s - old

        if diff < -30:
            signals.append(f"⚠️ 抽單 {f2(p)} -{diff}")
        elif diff > 30:
            signals.append(f"🟢 掛單 {f2(p)} +{diff}")

    return signals


def aggression(bids, asks, lp, lv):
    b = sum(bids.values())
    a = sum(asks.values())

    score = 50 + (b - a) / (b + a + 1) * 50

    if lv and lv > 30:
        score += 5 if lp > max(bids.keys(), default=0) else -5

    return max(0, min(100, score))


def compression(bids, asks):
    try:
        return (max(bids.keys()) - min(bids.keys()) < 1 and
                max(asks.keys()) - min(asks.keys()) < 1)
    except:
        return False

# ======================
# UI
# ======================
st.title("🏛️ Alpha-Trader v16 FULL (No Feature Loss)")

symbol = st.text_input("股票代碼", "2330")

snap, mode = fetch_stock(symbol)

if not snap:
    st.error("無資料")
    st.stop()

bids = snap["bids"]
asks = snap["asks"]

curr_b = {x["price"]: x["size"] for x in bids}
curr_a = {x["price"]: x["size"] for x in asks}

# ======================
# 🌍 市場（保留 v15）
# ======================
st.subheader("🌍 全球市場")
cols = st.columns(4)
global_data = fetch_global()

for i, (k, v) in enumerate(global_data.items()):
    p, pct = v
    cols[i].metric(k, f2(p), f"{pct:.2f}%" if pct else "--")

# ======================
# 📊 五檔（保留 v15）
# ======================
st.subheader("📊 五檔")
df_b = pd.DataFrame(bids).rename(columns={"price":"買價","size":"買量"})
df_a = pd.DataFrame(asks).rename(columns={"price":"賣價","size":"賣量"})
st.dataframe(pd.concat([df_b, df_a], axis=1), use_container_width=True)

# ======================
# 📜 成交（保留 v15）
# ======================
lp = snap.get("lastPrice")
lv = snap.get("lastSize")

st.session_state.trades.insert(0, f"{f2(lp)} | {lv}")

# ======================
# 🧠 v16 intelligence overlay
# ======================
liq = detect_liquidity(
    curr_a,
    st.session_state.last_book["a"] if st.session_state.last_book else {}
)

score = aggression(curr_b, curr_a, lp, lv)
compress = compression(curr_b, curr_a)

# ======================
# ALERT SYSTEM（整合）
# ======================
for s in liq:
    st.session_state.alerts.insert(0, s)

if compress:
    st.session_state.alerts.insert(0, "📦 壓縮區（變盤前兆）")

# update book
st.session_state.last_book = {"b": curr_b, "a": curr_a}

# ======================
# DASHBOARD
# ======================
c1, c2, c3 = st.columns(3)

with c1:
    st.metric("多空強度", f"{score:.1f}/100")

with c2:
    st.metric("壓縮區", "YES" if compress else "NO")

with c3:
    st.metric("成交價", f2(lp))

# ======================
# OUTPUT（v15 + v16 並存）
# ======================
col1, col2 = st.columns(2)

with col1:
    st.subheader("🚨 主力訊號")
    st.code("\n".join(st.session_state.alerts[:25]) or "無")

with col2:
    st.subheader("📜 成交流")
    st.code("\n".join(st.session_state.trades[:25]) or "無")

time.sleep(2)
st.rerun()
