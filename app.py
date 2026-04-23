import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- 1. 專業介面風格 (保留你最愛的 2:3 佈局) ---
st.set_page_config(page_title="富果極速狙擊手", layout="wide")
st.markdown("""
    <style>
    .stTable {font-size: 1.1rem !important;}
    .stDataFrame {height: 600px !important;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 側邊欄設定 ---
st.sidebar.header("⚡ 監控設定")
default_key = st.secrets.get("FUGLE_API_KEY", "")
api_key = st.sidebar.text_input("Fugle API Key", value=default_key, type="password")
symbol = st.sidebar.text_input("股票代號", value="2330").upper().strip()
refresh_rate = st.sidebar.slider("刷新間隔 (秒)", 1.0, 5.0, 2.0)

run_monitor = st.sidebar.toggle("🚀 啟動即時監控", value=False)

st.title(f"📊 {symbol} 行情監控系統")

# --- 3. 核心：自動路徑偵測引擎 ---
def get_data_v2(resource, target_symbol):
    """
    這是一個強大的自動適應函式，會嘗試所有可能的 Fugle API 路徑
    """
    # 測試路徑清單 (由新到舊)
    urls = [
        f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/{resource}/twse:{target_symbol}",
        f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/{resource}/tpex:{target_symbol}",
        f"https://api.fugle.tw/marketdata/v1/stock/intraday/{resource}?symbolId={target_symbol}&apiToken={api_key}"
    ]
    
    for url in urls:
        try:
            # 同時嘗試 Header 驗證與參數驗證
            headers = {"X-API-KEY": api_key}
            res = requests.get(url, headers=headers, timeout=3)
            if res.status_code == 200:
                data = res.json()
                # 處理 V1 與 V1.0 的資料結構差異
                if 'data' in data: return data['data'].get(resource) # V1
                return data # V1.0
        except:
            continue
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
        st.error("請在左側輸入 API KEY")
    else:
        tick_history = []
        
        # 建立一個佔位符顯示連線狀態
        status_bar = st.sidebar.empty()
        status_bar.info("📡 嘗試連線中...")

        while run_monitor:
            # 同步抓取
            ob = get_data_v2("orderbook", symbol)
            qt = get_data_v2("quote", symbol)

            # --- A. 渲染五檔 ---
            if ob and ('bids' in ob or 'asks' in ob):
                status_bar.success(f"✅ 連線正常: {datetime.now().strftime('%H:%M:%S')}")
                # 兼容不同 API 的欄位名稱
                bids_raw = ob.get('bids', [])
                asks_raw = ob.get('asks', [])
                
                df_asks = pd.DataFrame(asks_raw).sort_values('price', ascending=False)
                df_bids = pd.DataFrame(bids_raw).sort_values('price', ascending=False)
                
                if not df_asks.empty:
                    df_asks.columns = ['賣價', '賣量']
                    df_bids.columns = ['買價', '買量']
                    orderbook_area.table(
                        pd.concat([df_asks, df_bids], axis=0).reset_index(drop=True).style
                        .format("{:.2f}", subset=['賣價', '買價'])
                        .bar(subset=['賣量'], color='#FF4B4B', vmin=0)
                        .bar(subset=['買量'], color='#00C853', vmin=0)
                    )
            else:
                orderbook_area.warning("正在等待五檔數據... (若已盤後則不顯示)")

            # --- B. 渲染成交 ---
            if qt:
                p = qt.get('lastPrice')
                v = qt.get('lastSize')
                if p:
                    new_tick = {
                        "時間": datetime.now().strftime("%H:%M:%S"),
                        "成交價": f"{p:.2f}",
                        "單量": int(v)
                    }
                    # 避免重複顯示
                    if not tick_history or (new_tick['時間'] != tick_history[0]['時間']):
                        tick_history.insert(0, new_tick)
                    details_area.dataframe(pd.DataFrame(tick_history[:25]), use_container_width=True)
            else:
                details_area.info("正在等待成交明細...")

            time.sleep(refresh_rate)
else:
    st.info("👈 請開啟側邊欄的『啟動即時監控』。")
