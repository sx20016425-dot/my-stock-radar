import streamlit as st
import pandas as pd
import datetime
import requests
import yfinance as yf
import time

# ==============================
# 1. 基礎設定
# ==============================
st.set_page_config(page_title="Alpha-Trader v15 Phase 2", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# ==============================
# 2. 初始化
# ==============================
if "last_book" not in st.session_state:
    st.session_state.last_book = None
if "alerts" not in st.session_state:
    st.session_state.alerts = []
if "trades" not in st.session_state:
    st.session_state.trades = []
if "price_volume" not in st.session_state:
    st.session_state.price_volume = {}

# ==============================
# 3. 全球市場
# ==============================
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
        except:
            data[k] = (None, None)
    return data

def fetch_tx():
    try:
        url = f"https://api.fugle.tw/marketdata/v1.0/futures/snapshot/quotes/TXFR"
        r = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)
        if r.status_code == 200:
            d = r.json()
            return d.get("lastPrice"), d.get("changePercent")
    except:
        return None, None

# ==============================
# 4. 個股
# ==============================
def fetch_stock(symbol):
    try:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
        r = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

# ==============================
# 5. 主力邏輯
# ==============================
def calc_market_force(curr_b, curr_a):
    b = sum(curr_b.values())
    a = sum(curr_a.values())
    ratio = b / (a + 1)
    return b, a, ratio

def detect_breakout(lp, history_prices):
    if len(history_prices) < 5:
        return None
    recent_high = max(history_prices[-5:])
    recent_low = min(history_prices[-5:])
    
    if lp > recent_high:
        return "🚀 突破"
    elif lp < recent_low:
        return "💥 跌破"
    return None

def calc_cost_zone(price_volume):
    if not price_volume:
        return None
    total_vol = sum(price_volume.values())
    weighted = sum(float(p)*v for p, v in price_volume.items())
    return weighted / total_vol if total_vol > 0 else None

def market_filter(tx_pct, twii_pct):
    if tx_pct and twii_pct:
        if tx_pct > 0 and twii_pct > 0:
            return "多方市場"
        elif tx_pct < 0 and twii_pct < 0:
            return "空方市場"
    return "震盪"

# ==============================
# 6. UI
# ==============================
st.title("🏛️ Alpha-Trader v15 Phase 2")

symbol = st.text_input("股票代碼", "2330")
qty_limit = st.number_input("大單門檻", value=50)

# ===== 市場 =====
st.subheader("🌍 市場狀態")
cols = st.columns(5)

global_data = fetch_global()
tx_p, tx_pct = fetch_tx()

twii_pct = global_data.get("加權", (None, None))[1]

for i, (name, val) in enumerate(global_data.items()):
    p, pct = val
    if p:
        cols[i].metric(name, f"{p:,.0f}", f"{pct:.2f}%")

cols[4].metric("台指期", f"{tx_p}", f"{tx_pct}%")

market_state = market_filter(tx_pct, twii_pct)
st.info(f"市場判斷：{market_state}")

st.divider()

# ===== 個股 =====
snap = fetch_stock(symbol)

if snap:
    bids = snap.get("bids", [])
    asks = snap.get("asks", [])

    curr_b = {x['price']: x['size'] for x in bids}
    curr_a = {x['price']: x['size'] for x in asks}

    df = pd.DataFrame(bids)
    df2 = pd.DataFrame(asks)
    st.dataframe(pd.concat([df, df2], axis=1), use_container_width=True)

    # === 多空力道 ===
    b, a, ratio = calc_market_force(curr_b, curr_a)
    st.metric("多空比", f"{ratio:.2f}", f"B:{b} / S:{a}")

    # === 成交 ===
    lp = snap.get("lastPrice")
    lv = snap.get("lastSize")

    if lp:
        st.session_state.trades.insert(0, lp)

        # 成本計算
        ps = str(lp)
        st.session_state.price_volume[ps] = st.session_state.price_volume.get(ps, 0) + lv

        cost = calc_cost_zone(st.session_state.price_volume)

        # 突破
        history = st.session_state.trades[:20]
        signal = detect_breakout(lp, history)

        if signal:
            st.session_state.alerts.insert(0, signal)

        st.metric("主力成本", f"{cost:.2f}" if cost else "計算中")

    # 顯示
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🚨 訊號")
        st.code("\n".join(st.session_state.alerts[:20]))

    with col2:
        st.subheader("📜 成交")
        st.code("\n".join([str(x) for x in st.session_state.trades[:20]]))

# ==============================
# 7. 自動刷新
# ==============================
time.sleep(2)
st.rerun()
