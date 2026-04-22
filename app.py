import streamlit as st
import pandas as pd
import datetime
import time
import requests
import yfinance as yf

# --- 1. 配置與初始化 ---
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

st.set_page_config(page_title="專業操盤戰情室 - 期現貨連動版", layout="wide")

# 初始化 Session State
state_keys = {
    'price_stats': {},
    'index_data': {"price": 0, "percent": 0},
    'trade_history': [],
    'last_books_raw': None,
    'order_alerts': [],
    'tx_price': {"price": 0, "percent": 0}
}
for key, default in state_keys.items():
    if key not in st.session_state:
        st.session_state[key] = default

# --- 2. 核心數據函數 ---

def fetch_stock_data(symbol):
    """抓取個股即時快照"""
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
    headers = {"X-API-KEY": API_KEY}
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        return resp.json()
    except: return None

def get_market_indices():
    """抓取台指期、加權指數與亞洲盤"""
    results = {}
    # 常用代號：台指期近月 (^WTX), 日經 (^N225), 恒生 (^HSI)
    indices = {
        "台指期": "WTX=F",    # Yahoo Finance 台指期近月代號
        "日經 225": "^N225",
        "恒生指數": "^HSI"
    }
    for label, sym in indices.items():
        try:
            ticker = yf.Ticker(sym)
            info = ticker.fast_info
            price = info['last_price']
            prev = info['previous_close']
            results[label] = {
                "price": price,
                "percent": ((price - prev) / prev) * 100
            }
        except:
            results[label] = {"price": 0, "percent": 0}
    return results

# --- 3. UI 介面 ---

st.title("📊 專業操盤手實時戰情室 (期現貨連動)")

# 頂部大盤看板
mkt = get_market_indices()
idx_c1, idx_c2, idx_c3, idx_c4 = st.columns(4)
with idx_c1: 
    st.metric("台指期 (近月)", f"{mkt['台指期']['price']:.0f}", f"{mkt['台指期']['percent']:.2f}%")
with idx_c2:
    # 加權指數改由個股 Snapshot 帶回的數據更新，或顯示快取
    st.metric("台股加權", f"{st.session_state.index_data['price']}", f"{st.session_state.index_data['percent']}%")
with idx_c3: 
    st.metric("日經 225", f"{mkt['日經 225']['price']:.0f}", f"{mkt['日經 225']['percent']:.2f}%")
with idx_c4: 
    st.metric("恒生指數", f"{mkt['恒生指數']['price']:.0f}", f"{mkt['恒生指數']['percent']:.2f}%")

# 側邊欄
with st.sidebar:
    st.header("操作面板")
    stock_target = st.text_input("股票代號", value="2330").upper()
    run_switch = st.toggle("🚀 啟動即時監控", value=False)
    st.divider()
    alert_threshold = st.number_input("掛單變動警示閾值 (張)", value=50)
    if st.button("🗑️ 重置所有統計"):
        for key in ['price_stats', 'trade_history', 'order_alerts']: st.session_state[key] = [] if isinstance(state_keys[key], list) else {}
        st.session_state.last_books_raw = None
        st.rerun()

col_l, col_m, col_r = st.columns([1.1, 1.2, 0.7])

# --- 4. 監控與分析邏輯 ---

if run_switch:
    stock_data = fetch_stock_data(stock_target)
    
    if stock_data:
        # A. 五檔分析
        current_bids = {item['price']: item['size'] for item in stock_data.get('bids', [])}
        current_asks = {item['price']: item['size'] for item in stock_data.get('asks', [])}
        
        if st.session_state.last_books_raw:
            old_bids = st.session_state.last_books_raw['bids']
            old_asks = st.session_state.last_books_raw['asks']
            
            # 偵測壓單 (Ask) 與 支撐 (Bid)
            for price, size in current_asks.items():
                if price in old_asks:
                    diff = size - old_asks[price]
                    if abs(diff) >= alert_threshold:
                        action = "🔴 增加壓單" if diff > 0 else "⚪ 壓力撤單"
                        st.session_state.order_alerts.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {price} | {action} {abs(diff)}張")

            for price, size in current_bids.items():
                if price in old_bids:
                    diff = size - old_bids[price]
                    if abs(diff) >= alert_threshold:
                        action = "🟢 增加支撐" if diff > 0 else "⚪ 支撐撤單"
                        st.session_state.order_alerts.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {price} | {action} {abs(diff)}張")

        st.session_state.last_books_raw = {'bids': current_bids, 'asks': current_asks}

        # B. 更新加權指數數據
        st.session_state.index_data = {"price": stock_data.get('lastPrice', 0), "percent": stock_data.get('changePercent', 0)}
        
        with col_l:
            st.subheader("🏛️ 即時五檔")
            b_df = pd.DataFrame(stock_data.get('bids', [])).rename(columns={'price':'買價','size':'買量'})
            a_df = pd.DataFrame(stock_data.get('asks', [])).rename(columns={'price':'賣價','size':'賣量'})
            st.dataframe(pd.concat([b_df, a_df], axis=1), use_container_width=True)
            
            st.subheader("⚠️ 掛單動態分析")
            st.code("\n".join(st.session_state.order_alerts[:12]))

        with col_m:
            st.subheader("📈 分價成交分布")
            curr_p, curr_v = stock_data.get('lastPrice'), stock_data.get('lastSize')
            if curr_p:
                p_s = str(curr_p)
                if p_s not in st.session_state.price_stats: st.session_state.price_stats[p_s] = {'成交量':0}
                st.session_state.price_stats[p_s]['成交量'] += curr_v
            
            if st.session_state.price_stats:
                df = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index').sort_index(ascending=False)
                st.bar_chart(df)
                st.dataframe(df, use_container_width=True)

        with col_r:
            st.subheader("🔔 即時成交明細")
            if curr_p:
                st.session_state.trade_history.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {curr_p} | {curr_v}張")
            st.code("\n".join(st.session_state.trade_history[:20]))

    time.sleep(2)
    st.rerun()
