import streamlit as st
import pandas as pd
import yfinance as yf
import requests
import datetime
import time

# --- 頁面設定 ---
st.set_page_config(page_title="股票狙擊手監控", layout="wide")
st.title("🎯 股票狙擊手監控系統 (Web 版)")

# --- 參數設定 ---
EXCEL_FILE = 'sniper.xlsx'
# 建議將 LINE Token 放在 Streamlit 的 Secrets 設定中
CHANNEL_ACCESS_TOKEN = st.sidebar.text_input("LINE Token", type="password")
USER_ID = st.sidebar.text_input("LINE User ID")

def send_line_message(msg):
    if not CHANNEL_ACCESS_TOKEN or not USER_ID:
        return
    url = 'https://api.line.me/v2/bot/message/push'
    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {CHANNEL_ACCESS_TOKEN}'}
    payload = {'to': USER_ID, 'messages': [{'type': 'text', 'text': msg}]}
    requests.post(url, headers=headers, json=payload)

def get_current_price(ticker):
    try:
        stock = yf.Ticker(ticker)
        data = stock.history(period='1d')
        return data['Close'].iloc[-1] if not data.empty else None
    except:
        return None

# --- 讀取資料 ---
try:
    df = pd.read_excel(EXCEL_FILE)
    st.success("✅ 成功讀取股票清單")
except Exception as e:
    st.error(f"❌ 讀取 Excel 失敗: {e}")
    st.stop()

# --- 執行監控 ---
if st.button("立即執行掃描"):
    st.write(f"最後掃描時間: {datetime.datetime.now().strftime('%H:%M:%S')}")
    
    # 建立顯示用的表格
    results = []
    
    for index, row in df.iterrows():
        ticker = str(row['代號']).strip()
        name = str(row['公司名稱']).strip()
        target = float(row['賣出價'])
        
        current = get_current_price(ticker)
        
        status = "⚪ 觀察中"
        if current:
            if current >= target:
                status = "🚨 達標！"
                msg = f"🔔【賣出達標】{name}({ticker}) 現價:{current:.2f} 達標！"
                send_line_message(msg)
                st.warning(msg) # 在網頁上顯示警告
            
            results.append({
                "公司": name,
                "代號": ticker,
                "目標價": target,
                "目前股價": round(current, 2),
                "狀態": status
            })
        time.sleep(0.5)
    
    st.table(pd.DataFrame(results))

st.info("💡 提示：Streamlit Cloud 免費版不支援背景長時運行，建議手動點擊掃描或部署到支援 Cron Job 的平台。")
