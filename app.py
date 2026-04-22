import streamlit as st
import pandas as pd
import datetime
import time
import requests
import yfinance as yf

# --- 1. 配置與核心初始化 ---
# 此 API Key 已針對 REST 輪詢優化
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

st.set_page_config(page_title="專業操盤戰情室 | 全能穩定版", layout="wide", initial_sidebar_state="expanded")

# 建立魯棒性 (Robustness) 狀態容器：確保在 rerun 過程中數據不流失
state_keys = {
    'price_stats': {},        # 分價統計：{price: {'買入': 0, '賣出': 0}}
    'mkt_cache': {            # 全球大盤快取 (防止顯示 0)
        "台指期": {"p": "--", "pct": "0.00"}, "加權指數": {"p": "--", "pct": "0.00"},
        "TSM(ADR)": {"p": "0", "pct": "0"}, "日經 225": {"p": "0", "pct": "0"},
        "恒生指數": {"p": "0", "pct": "0"}, "標普 500": {"p": "0", "pct": "0"}
    },
    'trade_history': [],      # 成交明細流水帳
    'order_alerts': [],       # 主力掛單/抽單分析日誌
    'last_books_raw': None,   # 上一秒五檔快照
    'session_start': datetime.datetime.now().strftime("%H:%M:%S")
}

for key, default in state_keys.items():
    if key not in st.session_state:
        st.session_state[key] = default

# --- 2. 高可靠性數據引擎 ---

@st.cache_data(ttl=60) # 盤後快取一分鐘，盤中會隨 st.rerun 自動更新
def get_global_market_sync():
    """多源同步全球指標 (解決台指期與大盤 0 數據問題)"""
    targets = {
        "台指期": "WTX=F", "加權指數": "^TWII", 
        "TSM(ADR)": "TSM", "日經 225": "^N225", 
        "恒生指數": "^HSI", "標普 500": "^GSPC"
    }
    for label, sym in targets.items():
        try:
            ticker = yf.Ticker(sym)
            # 使用 history 取代 fast_info，確保休市時仍有最後收盤價
            hist = ticker.history(period="2d")
            if not hist.empty:
                last_p = hist['Close'].iloc[-1]
                prev_p = hist['Close'].iloc[-2] if len(hist) > 1 else last_p
                pct = ((last_p - prev_p) / prev_p) * 100
                if last_p > 0:
                    st.session_state.mkt_cache[label] = {
                        "p": f"{last_p:.2f}" if label in ["TSM(ADR)", "標普 500"] else f"{last_p:.0f}",
                        "pct": f"{pct:.2f}"
                    }
        except: pass
    return st.session_state.mkt_cache

def fetch_stock_snapshot(symbol):
    """Fugle REST API 高速快照"""
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{symbol}"
    headers = {"X-API-KEY": API_KEY}
    try:
        resp = requests.get(url, headers=headers, timeout=3)
        return resp.json() if resp.status_code == 200 else None
    except: return None

# --- 3. 戰情室介面佈局 ---

st.markdown(f"### 🚀 專業操盤手實時戰情室 <small>Session Start: {st.session_state.session_start}</small>", unsafe_allow_html=True)

# 第一層：全球市場連動指標 (Global Market Interconnectivity)
mkt = get_global_market_sync()
idx_cols = st.columns(6)
idx_labels = ["台指期", "加權指數", "TSM(ADR)", "日經 225", "恒生指數", "標普 500"]
for i, label in enumerate(idx_labels):
    with idx_cols[i]:
        st.metric(label, mkt[label]["p"], f"{mkt[label]['pct']}%")

# 側邊欄控制
with st.sidebar:
    st.header("🎯 監控配置")
    target_stock = st.text_input("輸入個股代號", value="2330").upper()
    monitor_on = st.toggle("開啟監控系統", value=False)
    st.divider()
    alert_qty = st.number_input("主力大單閾值 (張)", value=50, step=10)
    
    if st.button("🗑️ 清空統計數據", use_container_width=True):
        st.session_state.price_stats = {}
        st.session_state.trade_history = []
        st.session_state.order_alerts = []
        st.session_state.last_books_raw = None
        st.rerun()
    
    st.markdown("""---
    **操盤提醒：**
    1. **期現貨價差**：觀察台指期與加權漲跌幅差異。
    2. **抽單警告**：若壓單撤消失，留意向上突破。
    """)

# 第二層：核心交易數據 (Core Trading Data)
col_book, col_chart, col_trade = st.columns([1, 1.2, 0.8])

# --- 4. 監控邏輯與渲染 ---

if monitor_on:
    snap = fetch_stock_snapshot(target_stock)
    
    if snap:
        # A. 五檔量能異動分析 (Order Book Analysis)
        bids = {x['price']: x['size'] for x in snap.get('bids', [])}
        asks = {x['price']: x['size'] for x in snap.get('asks', [])}
        
        if st.session_state.last_books_raw:
            old_b, old_a = st.session_state.last_books_raw['b'], st.session_state.last_books_raw['a']
            # 賣盤：壓單監控
            for p, s in asks.items():
                if p in old_a and abs(s - old_a[p]) >= alert_qty:
                    msg = "🔴 壓單增加" if s > old_a[p] else "⚪ 壓力撤單"
                    st.session_state.order_alerts.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {p} | {msg} {abs(s-old_a[p])}張")
            # 買盤：支撐監控
            for p, s in bids.items():
                if p in old_b and abs(s - old_b[p]) >= alert_qty:
                    msg = "🟢 支撐增加" if s > old_b[p] else "⚪ 支撐撤單"
                    st.session_state.order_alerts.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {p} | {msg} {abs(s-old_b[p])}張")
        
        st.session_state.last_books_raw = {'b': bids, 'a': asks}

        # B. 多空力道邏輯 (Trade Force Logic)
        last_p, last_v = snap.get('lastPrice'), snap.get('lastSize')
        if last_p:
            ps = str(last_p)
            if ps not in st.session_state.price_stats: st.session_state.price_stats[ps] = {'買入': 0, '賣出': 0}
            
            # 主動買賣判定：成交價與五檔第一檔比對
            bid_1 = snap.get('bids', [{}])[0].get('price', 0)
            if last_p >= bid_1: st.session_state.price_stats[ps]['買入'] += last_v
            else: st.session_state.price_stats[ps]['賣出'] += last_v
            
            st.session_state.trade_history.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {last_p} | {last_v}張")

        # C. UI 渲染
        with col_book:
            st.subheader("🏛️ 五檔即時掛單")
            b_df = pd.DataFrame(snap.get('bids', [])).rename(columns={'price':'買價','size':'買量'})
            a_df = pd.DataFrame(snap.get('asks', [])).rename(columns={'price':'賣價','size':'賣量'})
            st.dataframe(pd.concat([b_df, a_df], axis=1), hide_index=True, use_container_width=True)
            
            st.subheader("⚠️ 主力動作監控")
            st.code("\n".join(st.session_state.order_alerts[:15]))

        with col_chart:
            st.subheader("📈 分價多空量能分布")
            if st.session_state.price_stats:
                df = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index').sort_index(ascending=False)
                st.bar_chart(df, color=["#FF4B4B", "#00CC96"]) # 🔴買入, 🟢賣出
                
                sum_buy = df['買入'].sum()
                sum_sell = df['賣出'].sum()
                st.metric("盤中多空淨量", f"{int(sum_buy - sum_sell)} 張", f"累計買入 {int(sum_buy)} / 賣出 {int(sum_sell)}")
                st.dataframe(df, use_container_width=True)

        with col_trade:
            st.subheader("🔔 即時明細")
            st.code("\n".join(st.session_state.trade_history[:30]))

    time.sleep(2) # 兼顧即時性與 API 負載
    st.rerun()
