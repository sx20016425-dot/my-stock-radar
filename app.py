# --- 3. 調整後的 WebSocket 執行緒功能 ---
def run_websocket(symbol, q):
    from fugle_marketdata import WebSocketClient
    
    def on_message(message):
        try:
            msg = json.loads(message)
            # 只要有任何訊息回來，就丟一個心跳訊號給主畫面
            q.put({"type": "heartbeat", "content": datetime.datetime.now().strftime("%H:%M:%S")})
            q.put({"type": "data", "content": msg})
        except: pass

    try:
        q.put({"type": "log", "content": "📡 正在連線..."})
        client = WebSocketClient(api_key=API_KEY)
        stock = client.stock
        
        stock.on('message', on_message)
        stock.on('connect', lambda: q.put({"type": "log", "content": "✅ 連線成功，等待數據..."}))
        stock.on('error', lambda e: q.put({"type": "log", "content": f"❌ 錯誤: {e}"}))
        
        stock.connect()
        
        # 針對非盤中時間，改用更顯眼的訂閱方式
        while True:
            q.put({"type": "log", "content": f"🔄 執行訂閱: {symbol}"})
            # 嘗試同時訂閱彙總資訊，這在收盤後比較容易有回傳
            stock.subscribe({"channel": "trades", "symbol": symbol})
            stock.subscribe({"channel": "books", "symbol": symbol})
            stock.subscribe({"channel": "ticker", "symbol": symbol}) # 增加 Ticker 頻道
            time.sleep(30) # 每 30 秒重新確認一次訂閱
            
    except Exception as e:
        q.put({"type": "log", "content": f"💥 崩潰: {str(e)}"})

# --- 4. 主循環對應修改 ---
# (在 while True 迴圈中加入 heartbeat 處理)
if 'last_heartbeat' not in st.session_state: st.session_state.last_heartbeat = "無"

# ... (中間省略，在處理 item 的地方加入)
                if item["type"] == "heartbeat":
                    st.session_state.last_heartbeat = item["content"]

# ... (在 sidebar 顯示)
with st.sidebar:
    st.write(f"最後通訊時間: {st.session_state.last_heartbeat}")
