import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import time
import random

st.set_page_config(page_title="Alpha-Trader v25 CONSOLIDATED WALL", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# =========================
# STATE
# =========================
for k in ["last_book", "alerts", "trades"]:
    if k not in st.session_state:
        st.session_state[k] = [] if k != "last_book" else None

# =========================
# FORMAT
# =========================
def f2(x):
    try:
        return "--" if x is None else f"{float(x):.2f}"
    except:
        return "--"

# =========================
# 🌍 GLOBAL
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
    for k,v in idx.items():
        try:
            df = yf.Ticker(v).history(period="2d")
            p = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2])
            out[k] = (p, (p-prev)/prev*100)
        except:
            out[k] = (None,None)
    return out

# =========================
# STOCK
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
        return None,"NONE"

    p = float(df["Close"].iloc[-1])

    return {
        "bids":[{"price":p-i*0.5,"size":random.randint(10,120)} for i in range(5)],
        "asks":[{"price":p+i*0.5,"size":random.randint(10,120)} for i in range(5)],
        "lastPrice":p,
        "lastSize":random.randint(1,80)
    },"SIM"

# =========================
# BOOK
# =========================
def book(bids,asks):
    bids = bids + [{} for _ in range(5-len(bids))]
    asks = asks + [{} for _ in range(5-len(asks))]

    return pd.DataFrame({
        "買價":[x.get("price") for x in bids],
        "買量":[x.get("size") for x in bids],
        "賣價":[x.get("price") for x in asks],
        "賣量":[x.get("size") for x in asks],
    })

# =========================
# FLOW
# =========================
def flow(curr,prev):
    sig=[]
    if not prev:
        return sig

    for i in range(2):
        cb=curr["bids"][i]
        pb=prev["bids"][i]
        ca=curr["asks"][i]
        pa=prev["asks"][i]

        if cb["size"]>pb["size"]*1.5:
            sig.append("🟢 買單加壓")

        if ca["size"]>pa["size"]*1.5:
            sig.append("🔴 賣單加壓")

        if cb["size"]<pb["size"]*0.5:
            sig.append("⚪ 買單抽離")

        if ca["size"]<pa["size"]*0.5:
            sig.append("⚪ 賣單撤單")

    return sig

# =========================
# TRADE TAPE
# =========================
def trade_feed(snap):
    lp = snap["lastPrice"]
    lv = snap["lastSize"]
    st.session_state.trades.insert(0, f"{lp:.2f} | {lv}張")

# =========================
# UI
# =========================
st.title("🏛️ Alpha-Trader v25 CONSOLIDATED INSTITUTION WALL")

symbol = st.text_input("股票代碼","2330")

# =========================
# GLOBAL
# =========================
g=fetch_global()
c=st.columns(4)

for i,(k,v) in enumerate(g.items()):
    p,pct=v
    c[i].metric(k,f2(p),f"{pct:.2f}%")

st.divider()

# =========================
# STOCK
# =========================
snap,mode=fetch_stock(symbol)

if not snap:
    st.error("NO DATA")
    st.stop()

bids=snap["bids"]
asks=snap["asks"]

lp=snap["lastPrice"]
lv=snap["lastSize"]

trade_feed(snap)

# =========================
# LAYOUT
# =========================
left,right=st.columns([1,2])

with left:
    st.subheader("📊 五檔")
    st.dataframe(book(bids,asks),use_container_width=True)

with right:

    r1,r2=st.columns([1,1])

    with r1:
        st.subheader("📈 Delta（15筆限制）")

        delta_data = flow(snap, st.session_state.last_book)
        st.code("\n".join(delta_data[:15]) or "無")

    # =========================
    # 🧠 SINGLE CONSOLIDATED WALL (ONLY ONE)
    # =========================
    with r2:

        st.subheader("🧠 機構監控牆（統一15筆）")

        flow_data = flow(snap, st.session_state.last_book)

        for f in flow_data:
            st.session_state.alerts.insert(0,f)

        alerts = st.session_state.alerts[:15]
        trades = st.session_state.trades[:15]

        wall_col1, wall_col2 = st.columns(2)

        with wall_col1:
            st.markdown("### 🚨 訊號")
            st.code("\n".join(alerts) or "無")

        with wall_col2:
            st.markdown("### 📡 即時成交")
            st.code("\n".join(trades) or "無")

# =========================
# METRICS
# =========================
st.divider()

c1,c2,c3=st.columns(3)

with c1:
    st.metric("成交價",f2(lp))

with c2:
    st.metric("成交量",lv)

with c3:
    st.metric("模式",mode)

# =========================
# SAVE STATE
# =========================
st.session_state.last_book = snap

# =========================
# LOOP
# =========================
time.sleep(2)
st.rerun()
