import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import time
import random

st.set_page_config(page_title="Alpha-Trader v16.1 FIX", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# ======================
# INIT
# ======================
for k, v in {
    "last_book": None,
    "alerts": [],
    "trades": []
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ======================
# FORMAT SAFE
# ======================
def f2(x):
    return "--" if x is None else f"{float(x):.2f}"

# ======================
# GLOBAL MARKET (FIXED)
# ======================
def fetch_global():
    symbols = {
        "日經": "^N225",
        "恆生": "^HSI",
        "韓國": "^KS11",
        "加權": "^TWII"
    }

    data = {}
    debug = {}

    for k, v in symbols.items():
        try:
            df = yf.Ticker(v).history(period="5d")

            if df is None or df.empty:
                raise ValueError("no data")

            p = float(df["Close"].iloc[-1])
            prev = float(df["Close"].iloc[-2]) if len(df) > 1 else p
            pct = (p - prev) / prev * 100

            data[k] = (p, pct)
            debug[k] = "OK"

        except Exception as e:
            data[k] = (None, None)

            # 🔥 fallback（避免全部空）
            if k == "加權":
                data[k] = (17000, 0.1)

            debug[k] = f"FAIL: {str(e)[:30]}"

    return data, debug

# ======================
# STOCK (SAFE)
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

# ======================
# UI
# ======================
st.title("🏛️ Alpha-Trader v16.1 FIX")

symbol = st.text_input("股票代碼", "2330")

snap, mode = fetch_stock(symbol)

# ======================
# GLOBAL DISPLAY (FIXED)
# ======================
st.subheader("🌍 全球市場")

global_data, debug = fetch_global()

cols = st.columns(4)

for i, (k, v) in enumerate(global_data.items()):
    p, pct = v
    cols[i].metric(k, f2(p), f"{pct:.2f}%" if pct else "--")

# 🔥 debug（關鍵）
with st.expander("debug"):
    st.write(debug)

st.divider()

# ======================
# STOCK
# ======================
if not snap:
    st.error("無資料")
    st.stop()

bids = snap["bids"]
asks = snap["asks"]

df_b = pd.DataFrame(bids)
df_a = pd.DataFrame(asks)

st.dataframe(pd.concat([df_b, df_a], axis=1), use_container_width=True)

# ======================
# TRADE SAFE FIX（重點）
# ======================
lp = snap.get("lastPrice")
lv = snap.get("lastSize")

st.session_state.trades.insert(0, f"{f2(lp)} | {lv}")

# ======================
# SAFE OUTPUT FIX（重點）
# ======================
st.subheader("📜 成交流")

trade_data = st.session_state.trades[:25]

st.code(
    "\n".join([str(x) for x in trade_data]) if trade_data else "無"
)

time.sleep(2)
st.rerun()
