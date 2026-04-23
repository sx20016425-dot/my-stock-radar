import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- 1. 頁面配置 (保留你的專業風格) ---
st.set_page_config(page_title="富果即時狙擊手", layout="wide")
st.markdown("<style>.stTable {font-size: 1.1rem !important;}</style>", unsafe_allow_html=True)

# --- 2. 側邊欄設定 ---
st.sidebar.header("🎯 監控參數")
default_key = st.secrets.get("FUGLE_API_KEY", "")
api_key = st.sidebar.text_input("Fugle API Key", value=default_key, type="password")
symbol = st.sidebar.text_input("股票代號", value="2330")
refresh_rate = st.sidebar.slider("更新頻率 (秒)", 1, 10, 3)

st.title(f"📊 {symbol} 即時行情監控")

# --- 3. 強大兼容性的抓取函式 ---
def fetch_fugle_smart(resource, target_symbol):
    """
    支援 V1.0 標準路徑，並加入詳細錯誤診斷
    """
    # 富果 V1.0 官方標準格式為大寫或小寫市場別
    markets = ["twse", "tpex"]
    headers = {"X-API-KEY": api_key, "Accept": "application/json"}
    
    for mkt in markets:
        # 測試格式 A: {mkt}:{symbol} (官方推薦)
        # 測試格式 B: {symbol} (部分舊版 Key 兼容)
        test_ids = [f"{mkt}:{target_symbol}", target_symbol]
        
        for tid in test_ids:
            url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/{resource}/{tid}"
            try:
                res = requests.get(url, headers=headers, timeout=5)
                if res.status_code == 200:
                    return res.json()
                elif res.status_code == 403:
                    st.sidebar.error("🚫 權限不足：請確認 API Key 已開通『行情資訊』權限")
                    return "AUTH_ERROR"
            except:
                continue
    return None

# --- 4. 介面佈局 (保留你最愛的 2:3 配置) ---
col1, col2 = st.columns([2, 3])
with col1:
    st.subheader("📢 最佳五檔 (Orderbook)")
    orderbook_area = st.empty()
with col2:
    st.subheader("⚡ 即時交易明細 (Ticks)")
    details_area = st.empty()

# --- 5. 執行監控 ---
if st.sidebar.button("🚀 啟動即時監控"):
    if not api_key:
        st.error("請輸入 API KEY")
    else:
        tick_history = []
        status_msg = st.sidebar.info("連線中...")
        
        while True:
            ob = fetch_fugle_smart("orderbook", symbol)
            quote = fetch_fugle_smart("quote", symbol)

            # 錯誤跳出機制
            if ob == "AUTH_ERROR": break

            # --- 處理五檔介面 ---
            if ob and 'bids' in ob and 'asks' in ob:
                status_msg.success(f"數據傳輸中: {datetime.now().strftime('%H:%M:%S')}")
                df_asks = pd.DataFrame(ob['asks']).sort_values('price', ascending=False)
                df_bids = pd.DataFrame(ob['bids']).sort_values('price', ascending=False)
                df_asks.columns, df_bids.columns = ['賣價', '賣量'], ['買價', '買量']
                
                orderbook_area.table(
                    pd.concat([df_asks, df_bids], axis=0).reset_index(drop=True).style
                    .format({"賣價": "{:.2f}", "買價": "{:.2f}"})
                    .bar(subset=['賣量'], color='#FF4B4B', vmin=0)
                    .bar(subset=['買量'], color='#00C853', vmin=0)
                )
            else:
                orderbook_area.warning("等待五檔數據... (若盤後則無數據)")

            # --- 處理明細介面 ---
            if quote:
                p, v = quote.get('lastPrice'), quote.get('lastSize')
                if p:
                    new_tick = {"時間": datetime.now().strftime("%H:%M:%S"), "成交價": f"{p:.2f}", "單量": int(v)}
                    if not tick_history or (new_tick['時間'] != tick_history[0]['時間']):
                        tick_history.insert(0, new_tick)
                    details_area.dataframe(pd.DataFrame(tick_history[:25]), use_container_width=True)
            else:
                details_area.info("等待成交明細...")

            time.sleep(refresh_rate)
