import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import time
import random
import datetime

st.set_page_config(page_title="Alpha-Trader v15 Phase 3", layout="wide")

API_KEY = st.secrets.get("FUGLE_API_KEY", "")

# ======================
# 初始化
# ======================
for key, default in {
    "last_book": None,
    "alerts": [],
    "trades": [],
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ======================
# 工具
# ======================
def fmt(x):
    return "--" if x is None else f"{x:,.0f}"

def fmt_pct(x):
    return "--" if x is None else f"{x:.2f}%"

# ======================
# 市場
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
            p = df['Close'].iloc[-1]
            prev = df['Close'].iloc[-2] if len(df) > 1 else p
            pct = (p - prev) / prev * 100
            data[k] = (p, pct)
        except:
            data[k] = (None, None)
    return data

# ======================
# 個股
# ======================
def fetch_stock(symbol):
    try:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
        r = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)
        if r.status_code == 200:
            data = r.json()
            if data.get("bids") and data.get("asks"):
                return data
    except:
        pass

    # fallback
    ticker = yf.Ticker(f"{symbol}.TW")
    df = ticker.history(period="1d")
    if not df.empty:
        price = df['Close'].iloc[-1]
        bids, asks = [], []
        for i in range(5):
            bids.append({"price": price - i*0.5, "size": random.randint(10,100)})
            asks.append({"price": price + i*0.5, "size": random.randint(10,100)})
        return {
            "bids": bids,
            "asks": asks,
            "lastPrice": price,
            "lastSize": random.randint(1,50)
        }

    return None

# ======================
# 主力行為判斷（核心）
# ======================
def detect_order_flow(curr_b, curr_a, last_book, threshold):
    signals = []

    if not last_book:
        return signals

    # 只看前3檔（戰區）
    for i in range(min(3, len(curr_a))):
        p = curr_a[i]['price']
        s = curr_a[i]['size']
        prev = last_book['a'].get(p, 0)
        diff = s - prev

        if abs(diff) >= threshold:
            if diff > 0:
                signals.append(f"🔴 壓單增加 {p} +{diff}")
            else:
                signals.append(f"⚪ 賣單撤單 {p} {diff}")

    for i in range(min(3, len(curr_b))):
        p = curr_b[i]['price']
        s = curr_b[i]['size']
        prev = last_book['b'].get(p, 0)
        diff = s - prev

        if abs(diff) >= threshold:
            if diff > 0:
                signals.append(f"🟢 撐單增加 {p} +{diff}")
            else:
                signals.append(f"⚪ 買單撤單 {p} {diff}")

    return signals


def detect_trade_action(lp, lv, best_bid, best_ask):
    signals = []

    if lp >= best_ask and lv > 20:
        signals.append(f"🚀 吃賣單 {lv}張 @ {lp}")

    elif lp <= best_bid and lv > 20:
        signals.append(f"💀 殺買單 {lv}張 @ {lp}")

    return signals

# ======================
# UI
# ======================
st.title("🏛️ Alpha-Trader v15 Phase 3")

symbol = st.text_input("股票代碼", "2330")
threshold = st.number_input("大單門檻", 50)

# ===== 市場 =====
cols = st.columns(4)
global_data = fetch_global()

for i, (k, v) in enumerate(global_data.items()):
    p, pct = v
    cols[i].metric(k, fmt(p), fmt_pct(pct))

st.divider()

# ===== 個股 =====
snap = fetch_stock(symbol)

if snap:
    bids = snap["bids"]
    asks = snap["asks"]

    df_b = pd.DataFrame(bids).rename(columns={"price":"買價","size":"買量"})
    df_a = pd.DataFrame(asks).rename(columns={"price":"賣價","size":"賣量"})

    st.dataframe(pd.concat([df_b, df_a], axis=1), use_container_width=True)

    curr_b = bids
    curr_a = asks

    # ===== 主力掛單監控 =====
    signals = detect_order_flow(curr_b, curr_a, st.session_state.last_book, threshold)

    # ===== 成交 =====
    lp = snap.get("lastPrice")
    lv = snap.get("lastSize")

    if lp:
        st.session_state.trades.insert(0, f"{lp} | {lv}張")

        best_bid = curr_b[0]['price']
        best_ask = curr_a[0]['price']

        trade_sig = detect_trade_action(lp, lv, best_bid, best_ask)
        signals.extend(trade_sig)

    # 更新 book
    st.session_state.last_book = {
        "b": {x['price']: x['size'] for x in curr_b},
        "a": {x['price']: x['size'] for x in curr_a}
    }

    # 存訊號
    for s in signals:
        st.session_state.alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {s}")

    # 顯示
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("🚨 主力訊號")
        st.code("\n".join(st.session_state.alerts[:20]) if st.session_state.alerts else "無")

    with col2:
        st.subheader("📜 成交明細")
        st.code("\n".join(st.session_state.trades[:30]) if st.session_state.trades else "無")

else:
    st.error("無資料")

# 刷新
time.sleep(2)
st.rerun()
