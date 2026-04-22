import streamlit as st
import pandas as pd
import asyncio
import datetime
import json

# --- 1. 導入 ---
try:
    from fugle_marketdata import WebSocketClient
except ImportError:
    st.error("❌ 導入失敗")
    st.stop()

# --- 2. 頁面配置 ---
st.set_page_config(page_title="盤口監控-事件驅動版", layout="wide")
API_KEY = st.secrets.get("FUGLE_API_KEY")

st.title("📈 實時盤口監控 (Event-Driven)")

with st.sidebar:
    target = st.text_input("股票代號", value="3042")
    threshold = st.number_input("大單張數 (>=)", value=50)
    btn_start = st.button("🚀 啟動監控", use_container_width=True)

col_left, col_right = st.columns(2)
book_ui = col_left.empty()
trade_ui = col_right.empty()

if 'history' not in st.session_state:
    st.session_state.history = []

# --- 3. 回調處理函數 ---
def handle_message(message):
    """處理 WebSocket 傳回的原始訊息"""
    try:
        msg = json.loads(message)
        event = msg.get("event")
        data = msg.get("data")
        
        if event == "data":
            # 判斷是五檔 (quote) 還是成交 (trade)
            # 根據 SDK 慣例，data 內通常含有 type 或可由欄位判斷
            if "bids" in data:
                # 處理五檔
                df = pd.DataFrame({
                    "買張": [b['size'] for b in data.get('bids', [])[:5]],
                    "買價": [b['price'] for b in data.get('bids', [])[:5]],
                    "賣價": [a['price'] for a in data.get('asks', [])[:5]],
                    "賣張": [a['size'] for a in data.get('asks', [])[:5]]
                })
                book_ui.table(df)
            
            elif "price" in data and "size" in data:
                # 處理成交
                p, v = data['price'], data['size']
                t = datetime.datetime.now().strftime("%H:%M:%S")
                icon = "🔥" if v >= threshold else "⚪"
                log = f"{icon} {t} | {p} | {v}張"
                st.session_state.history.insert(0, log)
                st.session_state.history = st.session_state.history[:15]
                trade_ui.code("\n".join(st.session_state.history))
                
    except Exception as e:
        pass

# --- 4. 核心連線邏輯 ---
async def start_monitor():
    # 根據你的屬性列表，直接操作 client.stock
    ws = WebSocketClient(api_key=API_KEY).stock
    
    try:
        # 步驟 A: 註冊訊息回調 (屬性中有 'on')
        # 這是 EventEmitter 模式，當訊息進來時執行 handle_message
        ws.on('message', handle_message)
        ws.on('error', lambda err: st.error(f"WS錯誤: {err}"))
        
        # 步驟 B: 建立連線 (屬性中有 'connect'，不帶 symbol)
        # 這裡通常是同步或包裝過的異步
        ws.connect()
        st.toast("🌐 伺服器連線中...")
        
        # 稍微等待連線認證完成
        await asyncio.sleep(2)
        
        # 步驟 C: 發送訂閱請求 (屬性中有 'subscribe')
        # 這是主動發送 JSON 給伺服器
        ws.subscribe({"symbol": target, "type": "quote"})
        ws.subscribe({"symbol": target, "type": "trade"})
        st.toast(f"✅ 已送出訂閱: {target}")
        
        # 步驟 D: 保持運行
        while True:
            await asyncio.sleep(1)
            
    except Exception as e:
        st.error(f"運行失敗: {e}")
        st.code(f"錯誤細節: {type(e)}")

# --- 5. 啟動入口 ---
if btn_start:
    # 由於這個 SDK 版本看起來偏向同步阻塞連線，我們用一個簡單的 task 跑它
    loop = asyncio.get_event_loop()
    loop.create_task(start_monitor())
    st.info("💡 監控已在背景啟動，請觀察下方數據更新。")
