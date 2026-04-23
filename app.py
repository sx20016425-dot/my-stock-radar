import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- 1. 基礎頁面配置 (保留原始風格) ---
st.set_page_config(page_title="富果即時狙擊手", layout="wide")

# 介面美化 CSS
st.markdown("""
    <style>
    .stTable {font-size: 1.1rem !important;}
    [data-testid="stMetricValue"] {font-size: 1.8rem !important;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 側邊欄參數模組 (保留並擴充) ---
st.sidebar.header("🎯 監控參數")
input_key = st.sidebar.text_input("Fugle API Key", type="password", help="若貼入整串，程式會自動擷取 Token 部分")
# 邏輯擴充：自動解析使用者貼入的複雜 Key 格式
api_key = input_key.strip().split(' ')[-1] if input_key else ""

symbol = st.sidebar.text_input("股票/ETF 代號", value="00981A").upper().strip()
refresh_rate = st.sidebar.slider("刷新頻率 (秒)", 1.0, 5.0, 2.0)

# 使用 Toggle 維持監控狀態穩定性
run_monitor = st.sidebar.toggle("🚀 啟動即時監控", value=False)

st.title(f"📊 {symbol} 行情即時監控")
status_log = st.sidebar.empty() # 狀態診斷模組

# --- 3. API 抓取模組 (功能擴充：自動適應路徑) ---
def fetch_fugle_data(resource, target_symbol, key):
    """
    擴充邏輯：自動循環測試 Fugle 所有可能的 ID 格式，解決 404 問題
    """
    # 測試路徑清單：ETF 通常需要 TSE:，一般股需要 twse: 或 tpex:
    test_ids = [
        f"TSE:{target_symbol}",   # 格式 A (ETF 專用)
        f"twse:{target_symbol}",  # 格式 B (上市)
        f"tpex:{target_symbol}",  # 格式 C (上櫃)
        target_symbol             # 格式 D (V1 舊版)
    ]
    
    headers = {"X-API-KEY": key, "Accept": "application/json"}
    
    for tid in test_ids:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/{resource}/{tid}"
        try:
            res = requests.get(url, headers=headers, timeout=3)
            if res.status_code == 200:
                return res.json(), tid  # 成功時回傳資料與對應的 ID
            elif res.status_code == 401:
                return "AUTH_ERROR", None
        except:
            continue
    return None, None

# --- 4. 介面佈局模組 (完全保留 2:3 架構) ---
col1, col2 = st.columns([2, 3])

with col1:
    st.subheader("📢 最佳五檔 (Orderbook)")
    orderbook_area = st.empty()

with col2:
    st.subheader("⚡ 即時交易明細 (Ticks)")
    details_area = st.empty()

# --- 5. 核心執行邏輯 (保留架構並優化迴圈) ---
if run_monitor:
    if not api_key:
        st.sidebar.error("❌ 請輸入 API KEY")
    else:
        tick_history = []
        confirmed_id = None # 用於鎖定路徑以提升後續速度
        
        while run_monitor:
            # 優先進行路徑匹配與數據抓取
            ob_data, success_id = fetch_fugle_data("orderbook", symbol, api_key)
            
            if ob_data == "AUTH_ERROR":
                st.sidebar.error("❌ Key 驗證失敗，請檢查 Token 是否正確")
                break
                
            if ob_data and 'bids' in ob_data:
                confirmed_id = success_id
                status_log.success(f"✅ 連線正常 ({confirmed_id})")
                
                # --- A. 五檔數據處理與渲染 ---
                asks = pd.DataFrame(ob_data['asks']).sort_values('price', ascending=False)
                bids = pd.DataFrame(ob_data['bids']).sort_values('price', ascending=False)
                
                if not asks.empty:
                    asks.columns, bids.columns = ['賣價', '賣量'], ['買價', '買量']
                    orderbook_area.table(
                        pd.concat([asks, bids], axis=0).reset_index(drop=True).style
                        .format("{:.2f}", subset=['賣價', '買價'])
                        .bar(subset=['賣量'], color='#FF4B4B', vmin=0)
                        .bar(subset=['買量'], color='#00C853', vmin=0)
                    )
                
                # --- B. 成交數據處理與渲染 (使用已確認的 ID) ---
                qt_url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/quote/{confirmed_id}"
                qt_res = requests.get(qt_url, headers={"X-API-KEY": api_key}, timeout=2)
                
                if qt_res.status_code == 200:
                    qt = qt_res.json()
                    p, v = qt.get('lastPrice'), qt.get('lastSize')
                    if p:
                        new_tick = {
                            "時間": datetime.now().strftime("%H:%M:%S"),
                            "成交價": f"{p:.2f}",
                            "量": int(v)
                        }
                        # 邏輯優化：避免重複時間點重複塞入資料
                        if not tick_history or (new_tick['時間'] != tick_history[0]['時間']):
                            tick_history.insert(0, new_tick)
                        details_area.dataframe(pd.DataFrame(tick_history[:30]), use_container_width=True)
            else:
                status_log.warning("⌛ 正在掃描正確路徑或等待盤中數據...")
                
            time.sleep(refresh_rate)
else:
    st.info("👈 請點擊側邊欄『啟動即時監控』開關開始運行。")
