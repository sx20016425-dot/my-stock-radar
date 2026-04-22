import streamlit as st
import pandas as pd
import datetime
import time
import requests
import yfinance as yf

# --- 1. 配置與初始化 ---
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGBmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

st.set_page_config(page_title="專業操盤戰情室 - 穩定版", layout="wide")

# 初始化狀態容器
if 'price_stats' not in st.session_state: st.session_state.price_stats = {}
if 'index_data' not in st.session_state: st.session_state.index_data = {"price": 0, "percent": 0}
if 'trade_history' not in st.session_state: st.session_state.trade_history = []
if 'last_books' not in st.session_state: st.session_state.last_books = pd.DataFrame()

# --- 2. 核心 REST 數據函數 ---

def fetch_stock_data(symbol):
    """抓取即時行情快照 (REST API)"""
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
    headers = {"X-API-KEY": API_KEY}
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        return resp.json()
    except:
        return None

def fetch_market_index():
    """抓取加權指數快照 (REST API)"""
    url = "https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/IX0001"
    headers = {"X-API-KEY": API_KEY}
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        return resp.json()
    except:
        return None

@st.cache_data(ttl=300)
def get_global_indices():
    """抓取亞洲指標 (日、港)"""
    results = {}
    indices = {"日經 225": "^N225", "恒生指數": "^HSI"}
    for label, sym in indices.items():
        try:
            t = yf.Ticker(sym).fast_info
            results[label] = {"price": t['last_price'], "percent": ((t['last_price']-t['previous_close'])/t['previous_close'])*100}
        except:
            results[label] = {"price": 0, "percent": 0}
    return results

# --- 3. UI 顯示介面 ---

st.title("📊 專業操盤手實時戰情室 (REST 穩定版)")

# 亞洲盤看板
global_data = get_global_indices()
idx_c1, idx_c2, idx_c3 = st.columns(3)
with idx_c1: st.metric("台股加權", f"{st.session_state.index_data['price']}", f"{st.session_state.index_data['percent']}%")
with idx_c2: st.metric("日經 225", f"{global_data['日經 225']['price']:.0f}", f"{global_data['日經 225']['percent']:.2f}%")
with idx_c3: st.metric("恒生指數", f"{global_data['恒生指數']['price']:.0f}", f"{global_data['恒生指數']['percent']:.2f}%")

# 側邊欄
with st.sidebar:
    st.header("操作面板")
    stock_target = st.text_input("股票代號", value="2330").upper()
    run_switch = st.toggle("🚀 啟動即時監控", value=False)
    st.divider()
    if st.button("🗑️ 重置統計數據"):
        st.session_state.price_stats = {}
        st.session_state.trade_history = []
        st.rerun()
    st.info("模式：REST API 輪詢 (高穩定度)")

col_l, col_m, col_r = st.columns([1, 1.3, 0.7])
with col_l:
    st.subheader("🏛️ 即時五檔")
    book_ui = st.empty()
with col_m:
    st.subheader("📈 分價成交分布")
    dist_chart = st.empty()
    dist_table = st.empty()
with col_r:
    st.subheader("🔔 即時明細 (每秒更新)")
    power_ui = st.empty()
    trade_list_ui = st.empty()

# --- 4. 監控邏輯 ---

if run_switch:
    while True:
        # 1. 抓取數據
        stock_data = fetch_stock_data(stock_target)
        market_data = fetch_market_index()
        
        if market_data:
            st.session_state.index_data = {"price": market_data.get('lastPrice'), "percent": market_data.get('changePercent')}

        if stock_data:
            # A. 處理五檔
            b_df = pd.DataFrame(stock_data.get('bids', [])).rename(columns={'price':'買價','size':'買量'})
            a_df = pd.DataFrame(stock_data.get('asks', [])).rename(columns={'price':'賣價','size':'賣量'})
            st.session_state.last_books = pd.concat([b_df, a_df], axis=1)
            
            # B. 處理成交 (REST 只有最後一筆，我們模擬累計)
            curr_p = stock_data.get('lastPrice')
            curr_v = stock_data.get('lastSize')
            if curr_p and curr_v:
                p_s = str(curr_p)
                if p_s not in st.session_state.price_stats: st.session_state.price_stats[p_s] = {'買入':0, '賣出':0}
                # REST 無法得知主動買賣，我們以目前價格是否高於平盤做簡易判斷，或直接歸類為單一統計
                st.session_state.price_stats[p_s]['買入'] += curr_v 
                
                now_str = datetime.datetime.now().strftime("%H:%M:%S")
                st.session_state.trade_history.insert(0, f"{now_str} | {curr_p} | {curr_v}張")

            # --- 更新 UI ---
            book_ui.dataframe(st.session_state.last_books, use_container_width=True)
            
            if st.session_state.price_stats:
                df = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index')
                df.index = df.index.astype(float)
                df = df.sort_index(ascending=False)
                dist_chart.bar_chart(df)
                dist_table.dataframe(df, use_container_width=True)
                
                t_vol = df['買入'].sum()
                power_ui.metric("目前累計成交量", f"{int(t_vol)} 張")

            trade_list_ui.code("\n".join(st.session_state.trade_history[:15]))

        time.sleep(2) # 輪詢間隔，可調整 1~3 秒
        st.rerun() # 強制刷新畫面
