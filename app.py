import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import numpy as np
import time
import datetime
import random

st.set_page_config(page_title="Alpha-Trader v27 OrderFlow Engine", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# =========================
# STATE
# =========================
def init():
    for k in ["book", "trades", "alerts"]:
        if k not in st.session_state:
            st.session_state[k] = []

init()

# =========================
# SAFE FORMAT
# =========================
def f(x):
    try:
        return f"{float(x):.2f}"
    except:
        return "--"

# =========================
# STOCK DATA
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

    # fallback SIM
    df = yf.Ticker(f"{symbol}.TW").history(period="1d")
    p = float(df["Close"].iloc[-1])

    return {
        "bids": [{"price": p-i*0.5, "size": random.randint(10,100)} for i in range(5)],
        "asks": [{"price": p+i*0.5, "size": random.randint(10,100)} for i in range(5)],
        "lastPrice": p,
        "lastSize": random.randint(1,80)
    }, "SIM"

# =========================
# ORDER FLOW ENGINE
# =========================
def detect_flow(curr, prev):
    alerts = []

    if not prev:
        return alerts

    # 1st & 2nd level
    for i in range(2):
        try:
            bp = curr["bids"][i]
            ap = curr["asks"][i]

            pb = prev["bids"][i]
            pa = prev["asks"][i]

            # 🟢 Bid aggression
            if bp["size"] > pb["size"] * 1.5:
                alerts.append(f"🟢 買盤加單 {bp['price']} +{bp['size']-pb['size']}")

            if bp["size"] < pb["size"] * 0.5:
                alerts.append(f"⚪ 買盤抽單 {bp['price']} -{pb['size']-bp['size']}")

            # 🔴 Ask pressure
            if ap["size"] > pa["size"] * 1.5:
                alerts.append(f"🔴 賣壓加單 {ap['price']} +{ap['size']-pa['size']}")

            if ap["size"] < pa["size"] * 0.5:
                alerts.append(f"⚪ 賣壓抽單 {ap['price']} -{pa['size']-ap['size']}")

        except:
            continue

    return alerts

# =========================
# TABLE
# =========================
def book(bids, asks):
    n = max(len(bids), len(asks), 5)

    bids = (bids or []) + [{} for _ in range(n - len(bids or []))]
    asks = (asks or []) + [{} for _ in range(n - len(asks or []))]

    return pd.DataFrame({
        "買價": [x.get("price") for x in bids],
        "買量": [x.get("size") for x in bids],
        "賣價": [x.get("price") for x in asks],
        "賣量": [x.get("size") for x in asks],
    })

# =========================
# UI
# =========================
st.title("🏛️ v27 Order Flow Intelligence Engine")

symbol = st.text_input("股票", "2330")

snap, mode = fetch(symbol)

bids = snap["bids"]
asks = snap["asks"]

# =========================
# FLOW DETECTION
# =========================
curr = {"bids": bids, "asks": asks}
prev = st.session_state.book

alerts = detect_flow(curr, prev)

for a in alerts:
    st.session_state.alerts.insert(0, a)

st.session_state.book = curr

# =========================
# ORDER BOOK
# =========================
st.subheader("📊 五檔攻防")

st.dataframe(book(bids, asks), use_container_width=True)

# =========================
# LAST TRADE
# =========================
st.subheader("📡 即時成交")

lp = snap.get("lastPrice")
lv = snap.get("lastSize")

st.metric("成交價", f(lp:.2f}" if lp else "--")
st.metric("成交量", lv)

st.session_state.trades.insert(0, f"{lp} | {lv}")

# =========================
# ALERTS
# =========================
st.subheader("🚨 Order Flow 警報")

st.code("\n".join(st.session_state.alerts[:20]) or "無")

# =========================
# LOOP
# =========================
time.sleep(2)
st.rerun()
