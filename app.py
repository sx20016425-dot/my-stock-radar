import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- 1. 介面配置 (保留所有模組與 2:3 架構) ---
st.set_page_config(page_title="富果即時狙擊手", layout="wide")

st.markdown("""
    <style>
    .stTable {font-size: 1.1rem !important;}
    [data-testid="stMetricValue"] {font-size: 1.8rem !important;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 側邊欄參數模組 ---
st.sidebar.header("🎯 監控參數")
input_key = st.sidebar.text_input("Fugle API Key", type="password", help="請貼入富果提供的 API Token")

# 自動解析：處理使用者可能貼入整串資訊的情況，只取最後一段 Token
api_key = input_key.strip().split(' ')[-1] if input_key else ""

symbol = st.sidebar.text_input("股票/ETF 代號", value="00981A").upper().strip()
refresh_rate = st.sidebar.slider("刷新頻率 (秒)", 1.0, 5.0, 2.0)

run_monitor = st.sidebar.toggle("🚀 啟動即時監控", value=False)

st.title(f"📊 {symbol} 行情即時監控")
status_log = st.sidebar.empty()

# 診斷區域：根據文章提到的 404/401 邏輯加強診斷
diag_expander = st.expander("🛠️ API 連線診斷報告 (Debug)", expanded=True)
diag_area = diag_expander.empty()

# --- 3. 核心 API 抓取模組 (參考 NestJS 實作邏輯：雙重路徑相容) ---
def fetch_fugle_smart(resource, target_symbol, key):
    """
    自動適應 V1.0 (RESTful) 與 V1 (Legacy) 請求格式
    """
    # 策略 A: V1.0 標準路徑 (測試不同市場標記)
    v10_ids = [target_symbol, f"TSE:{target_symbol}", f"twse:{target_symbol}"]
    
    headers = {"X-API-KEY": key, "Accept": "application/json"}
    debug_msgs = []

    # 1. 嘗試 V1.0 請求 (這是目前官方推薦的 Restful 格式)
    for tid in v10_ids:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/{resource}/{tid}"
        try:
            res = requests.get(url, headers=headers, timeout=2)
            debug_msgs.append(f"V1.0 {tid}: {res.status_code}")
            if res.status_code == 200:
                diag_area.code("\n".join(debug_msgs) + f"\n✅ V1.0 連線成功: {tid}")
                return res.json(), tid
        except:
            continue

    # 2. 嘗試 V1 請求 (參考文章中部分舊版 Key 支援的路徑)
    url_v1 = f"https://api.fugle.tw/marketdata/v1/stock/intraday/{resource}"
    try:
        res_v1 = requests.get(url_v1, params={"symbolId": target_symbol, "apiToken": key}, timeout=2)
        debug_msgs.append(f"V1 {target_symbol}: {res_v1.status_code}")
        if res_v1.status_code == 200:
            data = res_v1.json()
            diag_area.code("\n".join(debug_msgs) + "\n✅ V1 連線成功")
            # V1 的資料結構通常包在 data 欄位內
            return data.get('data', {}).get(resource), target_symbol
    except:
        pass

    diag_area.code("\n".join(debug_msgs) + "\n❌ 無法取得數據。請確認 API Key 權限。")
    return None, None

# --- 4. 介面佈局模組 (保留 2:3 比例) ---
col1, col2 = st.columns([2, 3])
with col1:
    st.subheader("📢 最佳五檔 (Orderbook)")
    orderbook_area = st.empty()
with col2:
    st.subheader("⚡ 即時交易明細 (Ticks)")
    details_area = st.empty()

# --- 5. 核心循環邏輯 ---
if run_monitor:
    if not api_key:
        st.sidebar.error("❌ 尚未輸入 API KEY")
    else:
        tick_history = []
        
        while run_monitor:
            # 獲取五檔與行情
            ob_data, success_id = fetch_fugle_smart("orderbook", symbol, api_key)
            qt_data, _ = fetch_fugle_smart("quote", symbol, api_key)
            
            # --- A. 五檔渲染 ---
            if ob_data and isinstance(ob_data, dict):
                status_log.success(f"✅ 數據更新中 ({success_id})")
                bids = ob_data.get('bids', [])
                asks = ob_data.get('asks', [])
                
                if bids and asks:
                    df_asks = pd.DataFrame(asks).sort_values('price', ascending=False)
                    df_bids = pd.DataFrame(bids).sort_values('price', ascending=False)
                    df_asks.columns, df_bids.columns = ['賣價', '賣量'], ['買價', '買量']
                    orderbook_area.table(
                        pd.concat([df_asks, df_bids], axis=0).reset_index(drop=True).style
                        .format("{:.2f}", subset=['賣價', '買價'])
                        .bar(subset=['賣量'], color='#FF4B4B').bar(subset=['買量'], color='#00C853')
                    )

            # --- B. 明細渲染 ---
            if qt_data and isinstance(qt_data, dict):
                price = qt_data.get('lastPrice')
                size = qt_data.get('lastSize')
                if price:
                    new_tick = {
                        "時間": datetime.now().strftime("%H:%M:%S"),
                        "價格": f"{price:.2f}",
                        "單量": int(size) if size else 0
                    }
                    if not tick_history or (new_tick['時間'] != tick_history[0]['時間']):
                        tick_history.insert(0, new_tick)
                    details_area.dataframe(pd.DataFrame(tick_history[:30]), use_container_width=True)
            
            time.sleep(refresh_rate)
else:
    st.info("👈 請開啟側邊欄的『啟動即時監控』開關。")
