import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- 1. 基礎頁面配置 (保留你的專業風格) ---
st.set_page_config(page_title="富果即時狙擊手", layout="wide")

# 隱藏右上方 Streamlit 選單使介面更乾淨 (選用)
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stTable {font-size: 1.2rem !important;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 側邊欄設定 ---
st.sidebar.header("🎯 監控參數")
# 優先嘗試從 Secrets 讀取，若無則顯示輸入框
default_key = st.secrets.get("FUGLE_API_KEY", "")
api_key = st.sidebar.text_input("Fugle API Key", value=default_key, type="password")
symbol = st.sidebar.text_input("股票代號 (如 2330)", value="2330")
refresh_rate = st.sidebar.slider("更新頻率 (秒)", 1, 5, 2)

st.title(f"📊 {symbol} 即時行情監控")

# --- 3. API 抓取函式 (加入除錯機制) ---
def fetch_data(resource, target_symbol):
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/{resource}/{target_symbol}"
    headers = {"X-API-KEY": api_key}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            return res.json()
        else:
            st.sidebar.error(f"API 錯誤: {res.status_code} - {res.text}")
            return None
    except Exception as e:
        st.sidebar.error(f"連線失敗: {e}")
        return None

# --- 4. 介面佈局 (保留你喜歡的 Layout) ---
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
        st.error("請輸入 API KEY 以啟動程式")
    else:
        st.sidebar.success(f"正在監控: {symbol}")
        tick_history = []
        
        # 使用 placeholder 進行不斷刷新的無窮迴圈
        while True:
            # 抓取資料
            ob = fetch_data("orderbook", symbol)
            quote = fetch_data("quote", symbol)

            if ob and quote:
                # --- A. 處理五檔 (保持階梯感與顏色) ---
                try:
                    # 賣單由高到低，買單由高到低
                    asks = pd.DataFrame(ob['asks']).sort_values('price', ascending=False)
                    bids = pd.DataFrame(ob['bids']).sort_values('price', ascending=False)
                    
                    # 重新命名與合併
                    asks.columns = ['賣價', '賣量']
                    bids.columns = ['買價', '買量']
                    
                    # 渲染到左側
                    orderbook_area.table(
                        pd.concat([asks, bids], axis=0).reset_index(drop=True).style
                        .format({"賣價": "{:.2f}", "買價": "{:.2f}"})
                        .bar(subset=['賣量'], color='#FF4B4B', vmin=0) # 賣單紅色
                        .bar(subset=['買量'], color='#00C853', vmin=0) # 買單綠色
                    )
                except Exception as e:
                    orderbook_area.warning("五檔資料解析中...")

                # --- B. 處理交易明細 (保持即時感) ---
                current_p = quote.get('lastPrice')
                current_v = quote.get('lastSize')
                
                if current_p:
                    new_tick = {
                        "時間": datetime.now().strftime("%H:%M:%S"),
                        "成交價": f"{current_p:.2f}",
                        "單量": int(current_v) if current_v else 0,
                    }
                    
                    # 避免重複紀錄同一筆資料 (簡易判斷)
                    if not tick_history or (new_tick['時間'] != tick_history[0]['時間']):
                        tick_history.insert(0, new_tick)
                    
                    # 渲染到右側
                    details_area.dataframe(pd.DataFrame(tick_history[:30]), use_container_width=True)
            
            # 強制停頓並進入下一輪重新跑 script 邏輯
            time.sleep(refresh_rate)
