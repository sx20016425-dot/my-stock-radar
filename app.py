import streamlit as st
import pandas as pd
import datetime
import requests
import yfinance as yf
from streamlit_autorefresh import st_autorefresh

# ==============================
# 1. 基礎設定
# ==============================
st.set_page_config(page_title="Alpha-Trader v15", layout="wide")

st_autorefresh(interval=2000, key="live_refresh")

# API KEY（請放到 secrets）
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

# ==============================
# 3. 市場資料（全球指數）
# ==============================
@st.cache_data(ttl=3)
def fetch_global_markets():
    symbols = {
        "日經225": "^N225",
        "恆生": "^HSI",
        "韓國": "^KS11",
        "加權": "^TWII"
    }

    data = {}
    for name, sym in symbols.items():
        try:
            df = yf.Ticker(sym).history(period="1d")
            if not df.empty:
                p = df['Close'].iloc[-1]
                prev = df['Close'].iloc[-2] if len(df) > 1 else p
                pct = (p - prev) / prev * 100
                data[name] = (p, pct)
        except:
            data[name] = (None, None)
    return data


@st.cache_data(ttl=2)
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
# 4. 個股資料
# ==============================
def fetch_stock_snapshot(symbol):
    try:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
        r = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None


# ==============================
# 5. 主力判斷引擎
# ==============================
def analyze_order_behavior(curr_b, curr_a, last_book, threshold):
    signals = []

    if not last_book:
        return signals

    for p, s in curr_a.items():
        prev = last_book['a'].get(p, 0)
        diff = s - prev
        if abs(diff) >= threshold:
            if diff > 0:
                signals.append(f"🔴 壓單增加 {p} +{diff}")
            else:
                signals.append(f"⚪ 壓單撤單 {p} {diff}")

    for p, s in curr_b.items():
        prev = last_book['b'].get(p, 0)
        diff = s - prev
        if abs(diff) >= threshold:
            if diff > 0:
                signals.append(f"🟢 支撐增加 {p} +{diff}")
            else:
                signals.append(f"⚪ 支撐撤單 {p} {diff}")

    return signals


def detect_trap(lp, lv, best_bid, best_ask, curr_b, curr_a):
    signals = []

    total_b = sum(curr_b.values())
    total_a = sum(curr_a.values())

    if lp >= best_ask and lv > 20 and total_a > total_b:
        signals.append("🚀 假壓盤（吸貨）")

    if lp <= best_bid and lv > 20 and total_b > total_a:
        signals.append("💀 假支撐（出貨）")

    return signals


# ==============================
# 6. UI
# ==============================
st.title("🏛️ Alpha-Trader v15 Phase 1")

symbol = st.text_input("股票代碼", value="2330")
qty_limit = st.number_input("大單門檻", value=50)

# ===== 全球市場 =====
st.subheader("🌍 全球市場")

cols = st.columns(5)
global_data = fetch_global_markets()
tx_p, tx_pct = fetch_tx()

for i, (name, val) in enumerate(global_data.items()):
    p, pct = val
    if p:
        cols[i].metric(name, f"{p:,.0f}", f"{pct:.2f}%")

cols[4].metric("台指期", f"{tx_p}", f"{tx_pct}%")

st.divider()

# ===== 個股監控 =====
st.subheader("📊 個股監控")

snap = fetch_stock_snapshot(symbol)

if snap:
    bids = snap.get("bids", [])
    asks = snap.get("asks", [])

    df_b = pd.DataFrame(bids).rename(columns={"price": "買價", "size": "買量"})
    df_a = pd.DataFrame(asks).rename(columns={"price": "賣價", "size": "賣量"})

    st.dataframe(pd.concat([df_b, df_a], axis=1), use_container_width=True)

    curr_b = {x['price']: x['size'] for x in bids}
    curr_a = {x['price']: x['size'] for x in asks}

    # === 主力行為 ===
    signals = analyze_order_behavior(curr_b, curr_a, st.session_state.last_book, qty_limit)

    for s in signals:
        st.session_state.alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {s}")

    # === 成交 ===
    lp = snap.get("lastPrice")
    lv = snap.get("lastSize")

    if lp:
        st.session_state.trades.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {lp} | {lv}張")

        best_bid = max(curr_b.keys()) if curr_b else 0
        best_ask = min(curr_a.keys()) if curr_a else 0

        trap = detect_trap(lp, lv, best_bid, best_ask, curr_b, curr_a)

        for s in trap:
            st.session_state.alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {s}")

    # 更新 book
    st.session_state.last_book = {'b': curr_b, 'a': curr_a}

# ===== 顯示 =====
col1, col2 = st.columns(2)

with col1:
    st.subheader("🚨 主力訊號")
    st.code("\n".join(st.session_state.alerts[:20]))

with col2:
    st.subheader("📜 成交明細")
    st.code("\n".join(st.session_state.trades[:30]))
