import streamlit as st
import pandas as pd
import datetime
import requests
import yfinance as yf
import time

st.set_page_config(page_title="Alpha-Trader v15 Stable", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# ======================
# 初始化
# ======================
for key, default in {
    "last_book": None,
    "alerts": [],
    "trades": [],
    "price_volume": {}
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ======================
# 安全數據抓取
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

def fetch_stock(symbol):
    try:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
        r = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

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

def detect_break(lp, history):
    if len(history) < 5:
        return None
    if lp > max(history[-5:]):
        return "🚀 突破"
    if lp < min(history[-5:]):
        return "💥 跌破"
    return None

# ======================
# UI
# ======================
st.title("🏛️ Alpha-Trader v15（穩定版）")

symbol = st.text_input("股票代碼", "2330")
qty_limit = st.number_input("大單門檻", 50)

# ===== 市場 =====
st.subheader("🌍 市場")

cols = st.columns(5)
global_data = fetch_global()
tx_p, tx_pct = fetch_tx()

twii_pct = global_data.get("加權", (None, None))[1]

for i, (k, v) in enumerate(global_data.items()):
    p, pct = v
    cols[i].metric(k, f"{p if p else '--'}", f"{pct:.2f}%" if pct else "--")

cols[4].metric("台指期", f"{tx_p if tx_p else '--'}", f"{tx_pct if tx_pct else '--'}")

if tx_pct and twii_pct:
    if tx_pct > 0 and twii_pct > 0:
        st.success("多方市場")
    elif tx_pct < 0 and twii_pct < 0:
        st.error("空方市場")
    else:
        st.warning("震盪")

st.divider()

# ===== 個股 =====
st.subheader("📊 個股監控")

snap = fetch_stock(symbol)

if not snap:
    st.warning("⚠️ 無法取得股票資料（可能非交易時間或 API 問題）")
else:
    bids = snap.get("bids", [])
    asks = snap.get("asks", [])

    if not bids or not asks:
        st.warning("⚠️ 無五檔資料")
    else:
        df_b = pd.DataFrame(bids).rename(columns={"price":"買價","size":"買量"})
        df_a = pd.DataFrame(asks).rename(columns={"price":"賣價","size":"賣量"})
        st.dataframe(pd.concat([df_b, df_a], axis=1), use_container_width=True)

        curr_b = {x['price']: x['size'] for x in bids}
        curr_a = {x['price']: x['size'] for x in asks}

        # 多空力道
        b_sum, a_sum, ratio = calc_force(curr_b, curr_a)
        st.metric("多空比", f"{ratio:.2f}", f"B:{b_sum} / S:{a_sum}")

        # 成交
        lp = snap.get("lastPrice")
        lv = snap.get("lastSize")

        if lp:
            st.session_state.trades.insert(0, lp)

            ps = str(lp)
            st.session_state.price_volume[ps] = st.session_state.price_volume.get(ps, 0) + (lv or 0)

            cost = calc_cost(st.session_state.price_volume)

            history = st.session_state.trades[:20]
            signal = detect_break(lp, history)

            if signal:
                st.session_state.alerts.insert(0, signal)

            st.metric("主力成本", f"{cost:.2f}" if cost else "--")

        # 顯示
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("🚨 訊號")
            st.code("\n".join(st.session_state.alerts[:20]) if st.session_state.alerts else "無訊號")

        with col2:
            st.subheader("📜 成交")
            st.code("\n".join([str(x) for x in st.session_state.trades[:20]]) if st.session_state.trades else "無成交")

# ======================
# 刷新
# ======================
time.sleep(2)
st.rerun()
