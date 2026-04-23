import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- 1. 介面設定 ---
st.set_page_config(page_title="富果極速監控", layout="wide")
st.markdown("<style>.stTable {font-size: 1.1rem !important;} .main {padding: 1rem;}</style>", unsafe_allow_html=True)

# --- 2. 側邊欄控制 ---
st.sidebar.header("⚡ 效能設定")
default_key = st.secrets.get("FUGLE_API_KEY", "")
api_key = st.sidebar.text_input("Fugle API Key", value=default_key, type="password")
symbol = st.sidebar.text_input("代號", value="2330")
# 降到最低 0.5 秒更新一次 (注意：免費版 Key 若更新太快可能會被暫時鎖定)
refresh_rate = st.sidebar.slider("刷新間隔 (秒)", 0.5, 3.0, 1.0, step=0.1)

st.title(f"📊 {symbol} 即時秒級監控")

# --- 3. 核心抓取邏輯 (固定路徑以加速) ---
@st.cache_data(ttl=3600)
def detect_market(target_symbol):
    """啟動時偵測一次市場，之後固定路徑減少延遲"""
    for mkt in ["twse", "tpex"]:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{mkt}:{target_symbol}"
        try:
            res = requests.get(url, headers={"X-API-KEY": api_key}, timeout=2)
            if res.status_code == 200: return mkt
        except: continue
    return "twse"

# --- 4. 介面佈局 (保留你最愛的風格) ---
col1, col2 = st.columns([2, 3])
with col1:
    st.subheader("📢 五檔掛單")
    orderbook_area = st.empty()
with col2:
    st.subheader("⚡ 成交明細")
    details_area = st.empty()

# --- 5. 執行監控 ---
if st.sidebar.button("🚀 開始極速監控"):
    market = detect_market(symbol)
    tick_history = []
    headers = {"X-API-KEY": api_key}
    
    # 使用單一 session 提升請求速度
    session = requests.Session()
    session.headers.update(headers)

    while True:
        try:
            # 同時發出請求 (盡可能縮短間隔)
            ob_res = session.get(f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/orderbook/{market}:{symbol}", timeout=1)
            qt_res = session.get(f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{market}:{symbol}", timeout=1)
            
            if ob_res.status_code == 200:
                ob = ob_res.json()
                df_asks = pd.DataFrame(ob['asks']).sort_values('price', ascending=False)
                df_bids = pd.DataFrame(ob['bids']).sort_values('price', ascending=False)
                df_asks.columns, df_bids.columns = ['賣價', '賣量'], ['買價', '買量']
                
                orderbook_area.table(
                    pd.concat([df_asks, df_bids], axis=0).reset_index(drop=True).style
                    .format("{:.2f}", subset=['賣價', '買價'])
                    .bar(subset=['賣量'], color='#FF4B4B', vmin=0)
                    .bar(subset=['買量'], color='#00C853', vmin=0)
                )

            if qt_res.status_code == 200:
                quote = qt_res.json()
                p, v = quote.get('lastPrice'), quote.get('lastSize')
                if p:
                    new_tick = {"時間": datetime.now().strftime("%H:%M:%S.%f")[:-4], "成交價": f"{p:.2f}", "量": int(v)}
                    # 只有當成交價格或量變動時才插入明細，節省渲染效能
                    if not tick_history or (new_tick['成交價'] != tick_history[0]['成交價'] or new_tick['量'] != tick_history[0]['量']):
                        tick_history.insert(0, new_tick)
                    details_area.dataframe(pd.DataFrame(tick_history[:20]), use_container_width=True, height=735)

        except Exception as e:
            pass # 忽略偶爾的連線超時
        
        time.sleep(refresh_rate)
