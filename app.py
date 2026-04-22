import streamlit as st
import pandas as pd
import time
import requests

# --- 1. 網頁基本配置 ---
st.set_page_config(page_title="大戶盤口攻守雷達", layout="wide")

# 強制讓頂部資訊列固定 (CSS 技巧)
st.markdown("""
    <style>
    .stApp { margin-top: -50px; }
    .sticky-header {
        position: fixed;
        top: 0;
        width: 100%;
        background-color: #0e1117;
        z-index: 1000;
        border-bottom: 2px solid #ff4b4b;
        padding: 10px;
        text-align: center;
    }
    </style>
""", unsafe_allow_html=True)

# --- 2. 讀取 API Key (從 Streamlit Secrets) ---
try:
    FUGLE_API_KEY = st.secrets["FUGLE_API_KEY"]
except:
    st.error("請在 Streamlit Secrets 中設定 FUGLE_API_KEY")
    st.stop()

# --- 3. 模擬台指期監控 (常駐頂部) ---
# 實際部署後，這裡可接富果指數 API 或抓取加權指期數據
st.markdown(f"""
    <div class="sticky-header">
        <h2 style="margin:0; color:white;">
            📉 台指期 (TX)：<span style="color:#ff4b4b;">20,450 (+120)</span> 
            | 狀態：<span style="color:#ff4b4b;">🔥 強勢多頭</span>
        </h2>
    </div>
""", unsafe_allow_html=True)

st.write("#") # 留白，避免內容被頂部列擋住

# --- 4. 側邊欄：設定監控個股 ---
st.sidebar.header("🎯 監控中心")
target_id = st.sidebar.text_input("輸入股票代號", value="3042")
refresh_sec = st.sidebar.slider("更新頻率 (秒)", 1, 10, 2)
threshold = st.sidebar.number_input("大單變動提醒門檻 (張)", value=50)

# --- 5. 主畫面佈局 ---
col1, col2 = st.columns([1, 1])

# 假設這是前一次的五檔數據，用來對比是否有「抽單」
if 'old_bids' not in st.session_state:
    st.session_state.old_bids = {}

with col1:
    st.subheader(f"🛡️ {target_id} 五檔掛單偵測")
    # 這裡顯示五檔數據
    # 實戰中會使用 fugle_marketdata 的 RestClient 抓取即時快照
    mock_order_book = {
        "買進價": [101, 100.5, 100, 99.5, 99],
        "買張": [80, 150, 400, 120, 250],
        "賣張": [45, 200, 180, 300, 50],
        "賣出價": [101.5, 102, 102.5, 103, 103.5]
    }
    df_book = pd.DataFrame(mock_order_book)
    st.table(df_book)
    
    # 模擬抽單監控邏輯
    current_best_ask_qty = 200 # 假設 102 元處的賣張
    old_qty = 350
    if (old_qty - current_best_ask_qty) >= threshold:
        st.warning(f"⚠️ 偵測到抽單！102.0 賣壓突然消失 {old_qty - current_best_ask_qty} 張")

with col2:
    st.subheader("⚔️ 成交明細與力道統計")
    # 統計當下攻守力道
    power_val = 65 # 假設買方力道 65%
    st.progress(power_val / 100)
    st.write(f"目前攻方 (外盤) 力道：{power_val}%")
    
    # 對戰紀錄 Log
    st.info(f"14:25:01 - {target_id} 突破 101.5，外盤連續敲擊 80 張 🔴")
    st.info(f"14:24:45 - 台指期急漲，個股買盤掛單同步轉強 🛡️")

# --- 6. 自動重新整理 ---
# 使用 Streamlit 的自帶機制讓頁面定時跳動更新數據
time.sleep(refresh_sec)
st.rerun()
