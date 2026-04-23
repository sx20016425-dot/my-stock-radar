import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- 1. 基礎頁面配置 ---
st.set_page_config(page_title="富果即時狙擊手", layout="wide")

st.markdown("""
    <style>
    .stTable {font-size: 1.2rem !important;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 側邊欄設定 ---
st.sidebar.header("🎯 監控參數")
default_key = st.secrets.get("FUGLE_API_KEY", "")
api_key = st.sidebar.text_input("Fugle API Key", value=default_key, type="password")
symbol = st.sidebar.text_input("股票代號 (例如 2330)", value="2330")
refresh_rate = st.sidebar.slider("更新頻率 (秒)", 1, 5, 2)

st.title(f"📊 {symbol} 即時行情監控")

# --- 3. 修正後的 API 抓取函式 (API V1.0 格式) ---
def fetch_data(resource, target_symbol):
    # 注意：Fugle V1.0 預設路徑通常直接接代號
    # 若依然 404，請確認開發者後台是否有開通該權限
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/{resource}/{target_symbol}"
    
    headers = {"X-API-KEY": api_key}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            return res.json()
        else:
            # 這裡會顯示具體的錯誤，方便我們除錯
            st.sidebar.warning(f"請求 {resource} 失敗: {res.status_code}")
            return None
    except Exception as e:
        st.sidebar.error(f"連線異常: {e}")
        return None

# --- 4. 介面佈局 ---
col1, col2 = st.columns([2, 3])

with col1:
    st.subheader("📢 最佳五檔 (Orderbook)")
    orderbook_area = st.empty()

with col2:
    st.subheader("⚡ 即時交易明細 (Ticks)")
    details_area = st.empty()

# --- 5. 啟動監控邏輯 ---
if st.sidebar.button("🚀 啟動即時監控"):
    if not api_key:
        st.error("請輸入 API KEY")
    else:
        tick_history = []
        
        while True:
            # 取得資料
            ob = fetch_data("orderbook", symbol)
            quote = fetch_data("quote", symbol)

            # --- A. 渲染五檔 (左側) ---
            if ob and 'bids' in ob and 'asks' in ob:
                asks = pd.DataFrame(ob['asks']).sort_values('price', ascending=False)
                bids = pd.DataFrame(ob['bids']).sort_values('price', ascending=False)
                asks.columns = ['賣價', '賣量']
                bids.columns = ['買價', '買量']
                
                orderbook_area.table(
                    pd.concat([asks, bids], axis=0).reset_index(drop=True).style
                    .format({"賣價": "{:.2f}", "買價": "{:.2f}"})
                    .bar(subset=['賣量'], color='#FF4B4B', vmin=0)
                    .bar(subset=['買量'], color='#00C853', vmin=0)
                )

            # --- B. 渲染明細 (右側) ---
            if quote:
                p = quote.get('lastPrice')
                v = quote.get('lastSize')
                if p is not None:
                    new_tick = {
                        "時間": datetime.now().strftime("%H:%M:%S"),
                        "成交價": f"{p:.2f}",
                        "單量": int(v) if v else 0,
                    }
                    if not tick_history or (new_tick['時間'] != tick_history[0]['時間']):
                        tick_history.insert(0, new_tick)
                    
                    details_area.dataframe(pd.DataFrame(tick_history[:30]), use_container_width=True)
            
            time.sleep(refresh_rate)
