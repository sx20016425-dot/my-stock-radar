import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# --- 1. 基礎頁面配置 (保留所有模組) ---
st.set_page_config(page_title="富果即時狙擊手", layout="wide")

st.markdown("""
    <style>
    .stTable {font-size: 1.1rem !important;}
    [data-testid="stMetricValue"] {font-size: 1.8rem !important;}
    </style>
    """, unsafe_allow_html=True)

# --- 2. 側邊欄參數模組 (保留並擴充) ---
st.sidebar.header("🎯 監控參數")
input_key = st.sidebar.text_input("Fugle API Key", type="password")
# 修正解析邏輯：確保取到正確的 Token
api_key = input_key.strip().split(' ')[-1] if input_key else ""

symbol = st.sidebar.text_input("股票/ETF 代號", value="2330").upper().strip()
refresh_rate = st.sidebar.slider("刷新頻率 (秒)", 1.0, 5.0, 1.0)

run_monitor = st.sidebar.toggle("🚀 啟動即時監控", value=False)

st.title(f"📊 {symbol} 行情即時監控")
status_log = st.sidebar.empty()

# 診斷區域
diag_expander = st.expander("🛠️ API 連線診斷報告 (Debug)", expanded=True)
diag_area = diag_expander.empty()

# --- 3. API 抓取模組 (核心修正：V1.0 與 V1 雙重相容) ---
def fetch_fugle_all_in_one(resource, target_symbol, key):
    """
    不刪功能，擴充自動降級邏輯。
    """
    # 測試清單：包含 V1.0 (新版) 與 V1 (舊版)
    # V1.0 路徑
    v10_ids = [f"TSE:{target_symbol}", f"twse:{target_symbol}", f"tpex:{target_symbol}"]
    
    headers = {"X-API-KEY": key, "Accept": "application/json"}
    debug_msgs = []

    # 1. 先測 V1.0
    for tid in v10_ids:
        url = f"https://api.fugle.tw/marketdata/v1.0/stock/intraday/{resource}/{tid}"
        try:
            res = requests.get(url, headers=headers, timeout=2)
            debug_msgs.append(f"V1.0 {tid}: {res.status_code}")
            if res.status_code == 200:
                diag_area.code("\n".join(debug_msgs) + f"\n✅ V1.0 成功: {tid}")
                return res.json(), tid
        except: continue

    # 2. 若 V1.0 失敗，測 V1 (舊版或免費版常見)
    # V1 格式：https://api.fugle.tw/marketdata/v1/stock/intraday/quote?symbolId=2330&apiToken=...
    url_v1 = f"https://api.fugle.tw/marketdata/v1/stock/intraday/{resource}"
    try:
        res_v1 = requests.get(url_v1, params={"symbolId": target_symbol, "apiToken": key}, timeout=2)
        debug_msgs.append(f"V1 {target_symbol}: {res_v1.status_code}")
        if res_v1.status_code == 200:
            data = res_v1.json()
            # V1 的資料包在 data 欄位裡
            diag_area.code("\n".join(debug_msgs) + "\n✅ V1 成功")
            return data.get('data', {}).get(resource), target_symbol
    except: pass

    diag_area.code("\n".join(debug_msgs) + "\n❌ 找不到資料，請檢查 API Key 權限")
    return None, None

# --- 4. 介面佈局模組 (保留 2:3 架構) ---
col1, col2 = st.columns([2, 3])
with col1:
    st.subheader("📢 最佳五檔 (Orderbook)")
    orderbook_area = st.empty()
with col2:
    st.subheader("⚡ 即時交易明細 (Ticks)")
    details_area = st.empty()

# --- 5. 核心執行邏輯 ---
if run_monitor:
    if not api_key:
        st.sidebar.error("❌ 請輸入 API KEY")
    else:
        tick_history = []
        
        while run_monitor:
            # 抓取五檔
            ob_data, success_id = fetch_fugle_all_in_one("orderbook", symbol, api_key)
            
            if ob_data:
                status_log.success(f"✅ 連線正常 ({success_id})")
                
                # --- A. 五檔處理 ---
                # 兼容 V1 與 V1.0 的欄位命名
                b_list = ob_data.get('bids') if isinstance(ob_data, dict) else None
                a_list = ob_data.get('asks') if isinstance(ob_data, dict) else None
                
                if b_list and a_list:
                    df_asks = pd.DataFrame(a_list).sort_values('price', ascending=False)
                    df_bids = pd.DataFrame(b_list).sort_values('price', ascending=False)
                    df_asks.columns, df_bids.columns = ['賣價', '賣量'], ['買價', '買量']
                    orderbook_area.table(
                        pd.concat([df_asks, df_bids], axis=0).reset_index(drop=True).style
                        .format("{:.2f}", subset=['賣價', '買價'])
                        .bar(subset=['賣量'], color='#FF4B4B').bar(subset=['買量'], color='#00C853')
                    )

                # --- B. 成交處理 (獨立呼叫確保不被五檔卡死) ---
                qt_data, _ = fetch_fugle_all_in_one("quote", symbol, api_key)
                if qt_data:
                    # 處理 V1/V1.0 欄位名稱差異
                    p = qt_data.get('lastPrice')
                    v = qt_data.get('lastSize')
                    if p:
                        new_tick = {
                            "時間": datetime.now().strftime("%H:%M:%S"),
                            "價格": f"{p:.2f}",
                            "量": int(v)
                        }
                        if not tick_history or (new_tick['時間'] != tick_history[0]['時間']):
                            tick_history.insert(0, new_tick)
                        details_area.dataframe(pd.DataFrame(tick_history[:30]), use_container_width=True)
            else:
                status_log.warning("⌛ 正在尋找有效路徑...")
                
            time.sleep(refresh_rate)
else:
    st.info("👈 請點擊側邊欄『啟動即時監控』開關。")
