import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import time
import random

st.set_page_config(page_title="Alpha-Trader v22 INSTITUTIONAL EXTENDED", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# =========================
# STATE (全部保留 + 擴充)
# =========================
for k in ["last_book", "alerts", "trades", "signals", "flow_state", "trend"]:
    if k not in st.session_state:
        st.session_state[k] = [] if k in ["alerts","trades","signals"] else None if k=="last_book" else {}

# =========================
# FORMAT
# =========================
def f2(x):
    try:
        return "--" if x is None else f"{float(x):.2f}"
    except:
        return "--"

# =========================
# 🌍 GLOBAL MARKET (不動)
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
# STOCK FETCH (不動)
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
# BOOK VIEW (不動)
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
# 📈 DELTA (保留)
# =========================
def delta(curr, prev):
    if not prev:
        return pd.DataFrame()

    rows=[]
    for i in range(2):
        cb=curr["bids"][i]
        pb=prev["bids"][i]
        ca=curr["asks"][i]
        pa=prev["asks"][i]

        rows.append([
            cb["price"],cb["size"]-pb["size"],
            ca["price"],ca["size"]-pa["size"]
        ])

    return pd.DataFrame(rows,columns=["買價","買Δ","賣價","賣Δ"])

# =========================
# 🧠 INSTITUTIONAL LAYER (新增核心)
# =========================
def institutional(curr, prev):
    sig=[]

    if not prev:
        return sig

    for i in range(2):

        cb=curr["bids"][i]
        pb=prev["bids"][i]

        ca=curr["asks"][i]
        pa=prev["asks"][i]

        # 🧲 吸籌
        if cb["size"] > pb["size"]*2:
            sig.append("🟢 主力持續吸籌")

        # 🔴 壓盤
        if ca["size"] > pa["size"]*2:
            sig.append("🔴 主力壓盤加重")

        # ⚡ 假流動性
        if cb["size"] < pb["size"]*0.4:
            sig.append("⚠️ 買盤瞬間消失（假跌破）")

        if ca["size"] < pa["size"]*0.4:
            sig.append("⚠️ 賣盤瞬間撤單（假突破）")

    # =========================
    # ⚡ 成交 vs 掛單壓力
    # =========================
    bid1=curr["bids"][0]["size"]
    ask1=curr["asks"][0]["size"]

    if bid1 > ask1*2:
        sig.append("🚀 買方攻擊性主導")

    if ask1 > bid1*2:
        sig.append("📉 賣方壓制盤面")

    return sig

# =========================
# UI
# =========================
st.title("🏛️ Alpha-Trader v22 INSTITUTIONAL FLOW EXTENSION")

symbol = st.text_input("股票代碼","2330")

# =========================
# 🌍 GLOBAL TOP
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

# =========================
# LAYOUT (不重構，只擴充)
# =========================
left,right=st.columns([1,2])

with left:
    st.subheader("📊 五檔")
    st.dataframe(book(bids,asks),use_container_width=True)

with right:

    r1,r2=st.columns(2)

    with r1:
        st.subheader("📈 Delta")
        st.dataframe(delta(snap,st.session_state.last_book),use_container_width=True)

    with r2:
        st.subheader("🧠 機構監控層")

        inst=institutional(snap,st.session_state.last_book)

        for s in inst:
            st.session_state.alerts.insert(0,s)

        st.code("\n".join(st.session_state.alerts[:25]) or "無")

# =========================
# METRICS
# =========================
st.divider()

m1,m2,m3=st.columns(3)

with m1:
    st.metric("成交價",f2(lp))

with m2:
    st.metric("成交量",lv)

with m3:
    st.metric("模式",mode)

# =========================
# SAVE STATE
# =========================
st.session_state.last_book=snap

# =========================
# LOOP
# =========================
time.sleep(2)
st.rerun()
