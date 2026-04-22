import streamlit as st
import pandas as pd
import datetime
import time
import requests
import yfinance as yf

# --- 1. 配置與初始化 ---
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

st.set_page_config(page_title="專業操盤戰情室 - 掛單監控版", layout="wide")

# 初始化狀態容器
if 'price_stats' not in st.session_state: st.session_state.price_stats = {}
if 'index_data' not in st.session_state: st.session_state.index_data = {"price": 0, "percent": 0}
if 'trade_history' not in st.session_state: st.session_state.trade_history = []
if 'last_books_raw' not in st.session_state: st.session_state.last_books_raw = None # 儲存前一次原始五檔
if 'order_alerts' not in st.session_state: st.session_state.order_alerts = [] # 掛單警告紀錄

# --- 2. 核心函數 ---

def fetch_stock_data(symbol):
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
    headers = {"X-API-KEY": API_KEY}
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        return resp.json()
    except: return None

@st.cache_data(ttl=300)
def get_global_indices():
    results = {}
    indices = {"日經 225": "^N225", "恒生指數": "^HSI"}
    for label, sym in indices.items():
        try:
            t = yf.Ticker(sym).fast_info
            results[label] = {"price": t['last_price'], "percent": ((t['last_price']-t['previous_close'])/t['previous_close'])*100}
        except: results[label] = {"price": 0, "percent": 0}
    return results

# --- 3. UI 介面 ---

st.title("📊 操盤手實時戰情室 (掛單/抽單監控版)")

global_data = get_global_indices()
idx_c1, idx_c2, idx_c3 = st.columns(3)
with idx_c1: st.metric("台股加權", f"{st.session_state.index_data['price']}", f"{st.session_state.index_data['percent']}%")
with idx_c2: st.metric("日經 225", f"{global_data['日經 225']['price']:.0f}", f"{global_data['日經 225']['percent']:.2f}%")
with idx_c3: st.metric("恒生指數", f"{global_data['恒生指數']['price']:.0f}", f"{global_data['恒生指數']['percent']:.2f}%")

with st.sidebar:
    st.header("操作面板")
    stock_target = st.text_input("股票代號", value="2330").upper()
    run_switch = st.toggle("🚀 啟動即時監控", value=False)
    st.divider()
    alert_threshold = st.number_input("大單變動警示閾值 (張)", value=50) # 超過50張變動就提醒
    if st.button("🗑️ 重置所有統計"):
        st.session_state.price_stats = {}
        st.session_state.trade_history = []
        st.session_state.order_alerts = []
        st.session_state.last_books_raw = None
        st.rerun()

col_l, col_m, col_r = st.columns([1.1, 1.2, 0.7])

# --- 4. 監控與分析邏輯 ---

if run_switch:
    stock_data = fetch_stock_data(stock_target)
    
    if stock_data:
        # A. 處理五檔變動分析 (掛單 vs 抽單)
        current_bids = {item['price']: item['size'] for item in stock_data.get('bids', [])}
        current_asks = {item['price']: item['size'] for item in stock_data.get('asks', [])}
        
        if st.session_state.last_books_raw:
            old_bids = st.session_state.last_books_raw['bids']
            old_asks = st.session_state.last_books_raw['asks']
            
            # 偵測賣盤 (Asks) 的變動 - 壓單或抽單
            for price, size in current_asks.items():
                if price in old_asks:
                    diff = size - old_asks[price]
                    if abs(diff) >= alert_threshold:
                        action = "🔴 增加掛單 (壓價格)" if diff > 0 else "⚪ 抽單 (撤銷壓力)"
                        st.session_state.order_alerts.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {price} | {action} {abs(diff)}張")

            # 偵測買盤 (Bids) 的變動 - 支撐或抽單
            for price, size in current_bids.items():
                if price in old_bids:
                    diff = size - old_bids[price]
                    if abs(diff) >= alert_threshold:
                        action = "🟢 增加買單 (強勢支撐)" if diff > 0 else "⚪ 抽單 (撤銷支撐)"
                        st.session_state.order_alerts.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {price} | {action} {abs(diff)}張")

        # 更新快照紀錄
        st.session_state.last_books_raw = {'bids': current_bids, 'asks': current_asks}

        # B. 常規數據更新
        st.session_state.index_data = {"price": stock_data.get('lastPrice'), "percent": stock_data.get('changePercent')}
        
        with col_l:
            st.subheader("🏛️ 五檔報價 (即時)")
            b_df = pd.DataFrame(stock_data.get('bids', [])).rename(columns={'price':'買價','size':'買量'})
            a_df = pd.DataFrame(stock_data.get('asks', [])).rename(columns={'price':'賣價','size':'賣量'})
            st.dataframe(pd.concat([b_df, a_df], axis=1), use_container_width=True)
            
            st.subheader("⚠️ 掛單/抽單動態")
            st.code("\n".join(st.session_state.order_alerts[:10]))

        with col_m:
            st.subheader("📈 分價成交分布")
            curr_p = stock_data.get('lastPrice')
            curr_v = stock_data.get('lastSize')
            if curr_p:
                p_s = str(curr_p)
                if p_s not in st.session_state.price_stats: st.session_state.price_stats[p_s] = {'量':0}
                st.session_state.price_stats[p_s]['量'] += curr_v
            
            df = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index').sort_index(ascending=False)
            st.bar_chart(df)
            st.dataframe(df, use_container_width=True)

        with col_r:
            st.subheader("🔔 即時明細")
            if curr_p:
                st.session_state.trade_history.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {curr_p} | {curr_v}張")
            st.code("\n".join(st.session_state.trade_history[:20]))

    time.sleep(2)
    st.rerun()
