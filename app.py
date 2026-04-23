import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- 1. 專業介面設定 ---
st.set_page_config(page_title="富果即時狙擊手", layout="wide")
st.markdown("<style>.stTable {font-size: 1.1rem !important;}</style>", unsafe_allow_html=True)

# --- 2. 側邊欄控制 ---
st.sidebar.header("⚡ 監控設定")
default_key = st.secrets.get("FUGLE_API_KEY", "")
api_key = st.sidebar.text_input("Fugle API Key", value=default_key, type="password")
symbol = st.sidebar.text_input("股票代號", value="2330").upper().strip()
refresh_rate = st.sidebar.slider("刷新間隔 (秒)", 1.0, 5.0, 2.0)

run_monitor = st.sidebar.toggle("🚀 啟動即時監控", value=False)

st.title(f"📊 {symbol} 行情即時追蹤")

# --- 3. 核心相容性抓取邏輯 ---
def fetch_fugle(resource, target_symbol):
    """
    使用 Fugle 最通用的 V1 路徑，避開容易 404 的 V1.0 標準路徑
    """
    # 格式：https://api.fugle.tw/marketdata/v1/stock/intraday/quote?symbolId=2330
    url = f"https://api.fugle.tw/marketdata/v1/stock/intraday/{resource}"
    params = {
        "symbolId": target_symbol,
        "apiToken": api_key # V1 版本通常使用 apiToken 參數
    }
    
    try:
        res = requests.get(url, params=params, timeout=5)
        if res.status_code == 200:
            return res.json()
        else:
            # 如果失敗，嘗試 V1.0 的新式 Header 驗證法
            res = requests.get(url, params={"symbolId": target_symbol}, headers={"X-API-KEY": api_key}, timeout=5)
            if res.status_code == 200:
                return res.json()
    except:
        pass
    return None

# --- 4. 介面佈局 ---
col1, col2 = st.columns([2, 3])
with col1:
    st.subheader("📢 最佳五檔")
    orderbook_area = st.empty()
with col2:
    st.subheader("⚡ 即時成交")
    details_area = st.empty()

# --- 5. 執行監控 ---
if run_monitor:
    if not api_key:
        st.error("❌ 尚未輸入 API KEY")
    else:
        tick_history = []
        # 使用 Session 優化速度
        session = requests.Session()
        
        while run_monitor:
            # 抓取五檔 (Orderbook) 與 行情 (Quote)
            # 注意：V1 的 resource 叫 'orderbook' 和 'quote'
            ob = fetch_fugle("orderbook", symbol)
            qt = fetch_fugle("quote", symbol)

            # --- A. 渲染五檔 ---
            if ob and 'data' in ob:
                d = ob['data'].get('orderbook', {})
                asks = pd.DataFrame(d.get('asks', [])).sort_values('price', ascending=False)
                bids = pd.DataFrame(d.get('bids', [])).sort_values('price', ascending=False)
                
                if not asks.empty:
                    asks.columns, bids.columns = ['賣價', '賣量'], ['買價', '買量']
                    orderbook_area.table(
                        pd.concat([asks, bids], axis=0).reset_index(drop=True).style
                        .format("{:.2f}", subset=['賣價', '買價'])
                        .bar(subset=['賣量'], color='#FF4B4B', vmin=0)
                        .bar(subset=['買量'], color='#00C853', vmin=0)
                    )

            # --- B. 渲染明細 ---
            if qt and 'data' in qt:
                q = qt['data'].get('quote', {})
                p, v = q.get('lastPrice'), q.get('lastSize')
                if p:
                    new_tick = {
                        "時間": datetime.now().strftime("%H:%M:%S"),
                        "成交價": f"{p:.2f}",
                        "單量": int(v)
                    }
                    if not tick_history or (new_tick['時間'] != tick_history[0]['時間'] or new_tick['成交價'] != tick_history[0]['成交價']):
                        tick_history.insert(0, new_tick)
                    details_area.dataframe(pd.DataFrame(tick_history[:25]), use_container_width=True)
            
            time.sleep(refresh_rate)
