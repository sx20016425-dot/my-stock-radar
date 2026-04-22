import streamlit as st
import pandas as pd
import datetime
import requests
import yfinance as yf
import time
import random

st.set_page_config(page_title="Alpha-Trader v15 FIX", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# 初始化
for key, default in {
    "last_book": None,
    "alerts": [],
    "trades": [],
    "price_volume": {}
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ======================
# 市場資料
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
            if not df.empty:
                p = df['Close'].iloc[-1]
                prev = df['Close'].iloc[-2] if len(df) > 1 else p
                pct = (p - prev) / prev * 100
                data[k] = (p, pct)
            else:
                data[k] = (None, None)
        except:
            data[k] = (None, None)
    return data

def fetch_tx():
    try:
        url = "https://api.fugle.tw/marketdata/v1.0/futures/snapshot/quotes/TXFR"
        r = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)
        if r.status_code == 200:
            d = r.json()
            return d.get("lastPrice"), d.get("changePercent")
    except:
        pass
    return None, None

# ======================
# 個股（核心修正）
# ======================
def fetch_stock(symbol):
    try:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
        r = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)
        if r.status_code == 200:
            data = r.json()
            if data.get("bids") and data.get("asks"):
                return data, "REAL"
    except:
        pass

    # 🔥 fallback（模擬五檔）
    try:
        ticker = yf.Ticker(f"{symbol}.TW")
        df = ticker.history(period="1d")
        if not df.empty:
            price = df['Close'].iloc[-1]

            bids = []
            asks = []

            for i in range(5):
                bids.append({
                    "price": round(price - i*0.5, 2),
                    "size": random.randint(10, 100)
                })
                asks.append({
                    "price": round(price + i*0.5, 2),
                    "size": random.randint(10, 100)
                })

            return {
                "bids": bids,
                "asks": asks,
                "lastPrice": price,
                "lastSize": random.randint(1, 50)
            }, "SIM"
    except:
        pass

    return None, "NONE"

# ======================
# 邏輯
# ======================
def calc_force(b, a):
    b_sum = sum(b.values())
    a_sum = sum(a.values())
    ratio = b_sum / (a_sum + 1)
    return b_sum, a_sum, ratio

def calc_cost(price_volume):
    if not price_volume:
        return None
    total = sum(price_volume.values())
    if total == 0:
        return None
    return sum(float(p)*v for p, v in price_volume.items()) / total

# ======================
# UI
# ======================
st.title("🏛️ Alpha-Trader v15（FIX版）")

symbol = st.text_input("股票代碼", "2330")

# 市場
st.subheader("🌍 市場")
cols = st.columns(5)

global_data = fetch_global()
tx_p, tx_pct = fetch_tx()

for i, (k, v) in enumerate(global_data.items()):
    p, pct = v
    cols[i].metric(k, f"{p if p else '--'}", f"{pct:.2f}%" if pct else "--")

cols[4].metric("台指期", f"{tx_p if tx_p else '--'}", f"{tx_pct if tx_pct else '--'}")

st.divider()

# 個股
st.subheader("📊 個股監控")

snap, mode = fetch_stock(symbol)

if snap:
    st.info(f"資料模式：{mode}")

    bids = snap.get("bids", [])
    asks = snap.get("asks", [])

    df_b = pd.DataFrame(bids)
    df_a = pd.DataFrame(asks)

    st.dataframe(pd.concat([df_b, df_a], axis=1), use_container_width=True)

    curr_b = {x['price']: x['size'] for x in bids}
    curr_a = {x['price']: x['size'] for x in asks}

    b, a, ratio = calc_force(curr_b, curr_a)
    st.metric("多空比", f"{ratio:.2f}", f"B:{b} / S:{a}")

    lp = snap.get("lastPrice")
    lv = snap.get("lastSize")

    if lp:
        st.session_state.trades.insert(0, lp)

        ps = str(lp)
        st.session_state.price_volume[ps] = st.session_state.price_volume.get(ps, 0) + (lv or 0)

        cost = calc_cost(st.session_state.price_volume)
        st.metric("主力成本", f"{cost:.2f}" if cost else "--")

else:
    st.error("完全無資料")

# 刷新
time.sleep(2)
st.rerun()
