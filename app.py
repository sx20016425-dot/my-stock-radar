import streamlit as st
import pandas as pd
import datetime
import time
import requests
import yfinance as yf

# --- 1. 配置與初始化 ---
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

st.set_page_config(page_title="專業操盤戰情室 - 數據強化版", layout="wide")

# 初始化狀態，防止 0 覆蓋舊數據
if 'price_stats' not in st.session_state: st.session_state.price_stats = {}
if 'mkt_cache' not in st.session_state: 
    st.session_state.mkt_cache = {
        "台指期": {"price": "--", "percent": "0.00"},
        "加權指數": {"price": "--", "percent": "0.00"}
    }
if 'trade_history' not in st.session_state: st.session_state.trade_history = []
if 'order_alerts' not in st.session_state: st.session_state.order_alerts = []
if 'last_books_raw' not in st.session_state: st.session_state.last_books_raw = None

# --- 2. 強化版數據抓取函數 ---

def get_market_data():
    """抓取台指期與大盤 (增加備援邏輯)"""
    results = {}
    # 台指期常用代號備案: WTX=F (近月), TX=F (連續), ^TWII (加權現貨)
    targets = {
        "台指期": "WTX=F",
        "加權指數": "^TWII",
        "日經 225": "^N225",
        "恒生指數": "^HSI"
    }
    
    for label, sym in targets.items():
        try:
            ticker = yf.Ticker(sym)
            # 使用 history 抓取最新一筆，比 fast_info 在盤後更穩定
            df = ticker.history(period="1d", interval="1m")
            if not df.empty:
                last_price = df['Close'].iloc[-1]
                prev_close = ticker.info.get('previousClose', last_price)
                change_pct = ((last_price - prev_close) / prev_close) * 100
                
                # 只有當數值大於 0 時才更新快取
                if last_price > 0:
                    st.session_state.mkt_cache[label] = {
                        "price": f"{last_price:.0f}" if "指數" in label or "期" in label else f"{last_price:.2f}",
                        "percent": f"{change_pct:.2f}"
                    }
        except:
            pass # 抓取失敗則保留上一次的快取數據
    return st.session_state.mkt_cache

def fetch_stock_snapshot(symbol):
    """抓取個股五檔與成交"""
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
    headers = {"X-API-KEY": API_KEY}
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        data = resp.json()
        if data and data.get('lastPrice'):
            return data
    except:
        return None

# --- 3. UI 佈局 ---

st.title("📊 專業操盤手實時戰情室 (數據穩定版)")

# 頂部大盤看板 (直接讀取強化快照)
mkt = get_market_data()
c1, c2, c3, c4 = st.columns(4)
with c1: st.metric("台指期 (TXF)", mkt["台指期"]["price"], f"{mkt['台指期']['percent']}%")
with c2: st.metric("台股加權 (TSE)", mkt["加權指數"]["price"], f"{mkt['加權指數']['percent']}%")
with c3: st.metric("日經 225", mkt.get("日經 225", {}).get("price", "--"), f"{mkt.get('日經 225', {}).get('percent', '0')}%")
with c4: st.metric("恒生指數", mkt.get("恒生指數", {}).get("price", "--"), f"{mkt.get('恒生指數', {}).get('percent', '0')}%")

# 側邊控制
with st.sidebar:
    st.header("監控參數")
    stock_target = st.text_input("輸入個股代號", value="2330").upper()
    run_switch = st.toggle("🚀 啟動即時監控", value=False)
    st.divider()
    alert_val = st.number_input("掛單異動警示 (張)", value=50)
    if st.button("🗑️ 清除所有紀錄"):
        st.session_state.price_stats = {}
        st.session_state.trade_history = []
        st.session_state.order_alerts = []
        st.session_state.last_books_raw = None
        st.rerun()
    
    # 診斷資訊
    st.write("---")
    st.caption(f"最後檢查時間: {datetime.datetime.now().strftime('%H:%M:%S')}")
    if run_switch:
        st.success("數據輪詢中...")
    else:
        st.warning("監控已停止")

# 主畫面佈局
col_l, col_m, col_r = st.columns([1.1, 1.2, 0.7])

# --- 4. 監控邏輯 ---

if run_switch:
    data = fetch_stock_snapshot(stock_target)
    
    if data:
        # A. 五檔異動分析 (壓單/支撐/抽單)
        curr_b = {item['price']: item['size'] for item in data.get('bids', [])}
        curr_a = {item['price']: item['size'] for item in data.get('asks', [])}
        
        if st.session_state.last_books_raw:
            old_b = st.session_state.last_books_raw['bids']
            old_a = st.session_state.last_books_raw['asks']
            
            # 比對賣盤變動 (壓力)
            for p, s in curr_a.items():
                if p in old_a:
                    diff = s - old_a[p]
                    if abs(diff) >= alert_val:
                        tag = "🔴 壓單增加" if diff > 0 else "⚪ 壓力抽單"
                        st.session_state.order_alerts.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {p} | {tag} {abs(diff)}張")

            # 比對買盤變動 (支撐)
            for p, s in curr_b.items():
                if p in old_b:
                    diff = s - old_b[p]
                    if abs(diff) >= alert_val:
                        tag = "🟢 支撐增加" if diff > 0 else "⚪ 支撐抽單"
                        st.session_state.order_alerts.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {p} | {tag} {abs(diff)}張")

        st.session_state.last_books_raw = {'bids': curr_b, 'asks': curr_a}

        # B. 渲染 UI
        with col_l:
            st.subheader("🏛️ 即時五檔")
            b_df = pd.DataFrame(data.get('bids', [])).rename(columns={'price':'買價','size':'買量'})
            a_df = pd.DataFrame(data.get('asks', [])).rename(columns={'price':'賣價','size':'賣量'})
            st.dataframe(pd.concat([b_df, a_df], axis=1), use_container_width=True)
            st.subheader("⚠️ 掛單動態分析")
            st.code("\n".join(st.session_state.order_alerts[:15]))

        with col_m:
            st.subheader("📈 分價成交分布")
            cp, cv = data.get('lastPrice'), data.get('lastSize')
            if cp:
                ps = str(cp)
                if ps not in st.session_state.price_stats: st.session_state.price_stats[ps] = 0
                st.session_state.price_stats[ps] += cv
            
            if st.session_state.price_stats:
                df = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index', columns=['成交量']).sort_index(ascending=False)
                st.bar_chart(df)
                st.dataframe(df, use_container_width=True)

        with col_r:
            st.subheader("🔔 即時成交明細")
            if cp:
                st.session_state.trade_history.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {cp} | {cv}張")
            st.code("\n".join(st.session_state.trade_history[:25]))

    time.sleep(2)
    st.rerun()
