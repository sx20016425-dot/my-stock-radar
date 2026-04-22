import streamlit as st
import pandas as pd
import datetime
import time
import requests
import yfinance as yf

# --- 1. 專業介面與剛性框架配置 ---
st.set_page_config(page_title="Alpha-Trader Ultimate v12.0", layout="wide", initial_sidebar_state="collapsed")

# 注入 CSS：確保版面寬度與黑色質感，並固定 Placeholder 最小高度防止閃爍
st.markdown("""
    <style>
    .main { background-color: #0D1117; }
    .stMetric { background: #161B22; padding: 15px; border-radius: 10px; border: 1px solid #30363D; }
    [data-testid="stMetricValue"] { font-size: 24px !important; color: #58A6FF !important; }
    .stCodeBlock { background-color: #010409 !important; border: 1px solid #30363D !important; min-height: 280px !important; }
    h3 { color: #8B949E; font-size: 14px !important; font-weight: 600; border-left: 4px solid #58A6FF; padding-left: 10px; margin: 20px 0 10px 0; }
    .stDataFrame { border: 1px solid #30363D !important; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心初始化 (確保所有邏輯變數在啟動時即存在) ---
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

state_defaults = {
    'trades': [],        # 即時成交明細
    'alerts': [],        # 大單異動警報
    'stats': {},         # 分價量能數據
    'last_book': None,   # 上一次五檔快照 (用於對比異動)
    'mkt_cache': {k: {"p": "--", "pct": "0.00"} for k in ["台指期", "加權指數", "TSM", "N225", "GSPC"]}
}

for key, value in state_defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value

# --- 3. 數據救援引擎 (解決狀態欄缺失) ---

def fetch_market_safe(symbol, is_future=False):
    """雙引擎救援：Fugle 優先，Yahoo 墊後"""
    try:
        path = "futures" if is_future else "stock"
        url = f"https://api.fugle.tw/marketdata/v1.0/{path}/snapshot/quotes/{symbol}"
        r = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)
        if r.status_code == 200:
            d = r.json()
            if d.get('lastPrice'): return d.get('lastPrice'), d.get('changePercent')
    except: pass
    
    # Yahoo 救援邏輯
    try:
        y_map = {"TXFR": "WTX=F", "IX0001": "^TWII"}
        y_sym = y_map.get(symbol, symbol)
        t = yf.Ticker(y_sym)
        df = t.history(period="1d")
        if not df.empty:
            p = df['Close'].iloc[-1]
            prev = t.info.get('previousClose', p)
            return p, ((p - prev) / prev) * 100
    except: pass
    return None, None

def fetch_aronhack_candles(symbol):
    """Aronhack 教學：獲取今日 1 分 K 歷史數據"""
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    url = f"https://api.fugle.tw/marketdata/v1.0/stock/candles?symbol={symbol}&from={today}&to={today}&fields=open,high,low,close,volume"
    try:
        r = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=2)
        if r.status_code == 200:
            df = pd.DataFrame(r.json().get('data', []))
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
                return df.sort_values('date')
    except: pass
    return pd.DataFrame()

# --- 4. 畫面渲染：靜態佈局 (確保功能區塊不消失) ---

st.markdown("## 🏛️ Alpha-Trader <span style='color:#58A6FF'>Ultimate Professional v12.0</span>", unsafe_allow_html=True)

# A. 頂部狀態看板 (核心指數)
m_cols = st.columns(5)
sync_targets = [("台指期", "TXFR", True), ("加權指數", "IX0001", False), ("TSM(ADR)", "TSM", False), ("日經 225", "^N225", False), ("標普 500", "^GSPC", False)]

for i, (name, sym, fut) in enumerate(sync_targets):
    p, c = fetch_market_safe(sym, is_future=fut)
    if p: st.session_state.mkt_cache[name] = {"p": f"{p:,.2f}" if "ADR" in name else f"{p:,.0f}", "pct": f"{c:,.2f}"}
    m_cols[i].metric(name, st.session_state.mkt_cache[name]["p"], f"{st.session_state.mkt_cache[name]['pct']}%")

st.divider()

# B. 側邊控制
with st.sidebar:
    st.header("⚙️ 終端核心設定")
    target_stock = st.text_input("監控標的代碼", value="2330").upper()
    monitor_switch = st.toggle("啟動 LIVE DATA FEED", value=True)
    alert_threshold = st.number_input("大單監控門檻 (張)", value=50)
    if st.button("🗑️ 重置當前數據"):
        st.session_state.trades = []; st.session_state.alerts = []; st.session_state.stats = {}; st.session_state.last_book = None; st.rerun()

# C. 主版面：Placeholder 預建 (確保表格、價格欄位永遠顯示標題)
col_left, col_right = st.columns([2.3, 0.7])

with col_left:
    st.markdown("<h3>📈 今日分鐘 K 線走勢 (Aronhack 歷史整合)</h3>", unsafe_allow_html=True)
    kline_ui = st.empty()
    
    sub_l, sub_r = st.columns(2)
    with sub_l:
        st.markdown("<h3>🏛️ 五檔即時報價 (買價/買量 | 賣價/賣量)</h3>", unsafe_allow_html=True)
        book_ui = st.empty()
        # 初始化顯示空表格頭，防止畫面消失
        book_ui.dataframe(pd.DataFrame(columns=['買價', '買量', '賣價', '賣量']), use_container_width=True)
        
    with sub_r:
        st.markdown("<h3>🚨 主力掛單異動監控</h3>", unsafe_allow_html=True)
        alert_ui = st.empty()
        alert_ui.code("Waiting for market signal...", language="bash")
    
    st.markdown("<h3>📊 多空分價成交量能統計</h3>", unsafe_allow_html=True)
    chart_ui = st.empty()
    force_ui = st.empty()

with col_right:
    st.markdown("<h3>🔔 即時成交明細 (Time & Sales)</h3>", unsafe_allow_html=True)
    trade_ui = st.empty()
    trade_ui.code("--- Ready ---", language="python")

# --- 5. 執行循環：全邏輯注入 ---

if monitor_switch:
    try:
        # 1. 歷史 K 線 (Aronhack 教學邏輯)
        df_k = fetch_aronhack_candles(target_stock)
        if not df_k.empty:
            kline_ui.line_chart(df_k.set_index('date')['close'], height=250)

        # 2. 獲取即時數據 (Fugle Snapshot)
        headers = {"X-API-KEY": API_KEY}
        res = requests.get(f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{target_stock}", headers=headers, timeout=2)
        
        if res.status_code == 200:
            snap = res.json()
            
            # A. 五檔邏輯：合併對稱表格
            b_df = pd.DataFrame(snap.get('bids', [])).rename(columns={'price':'買價','size':'買量'})
            a_df = pd.DataFrame(snap.get('asks', [])).rename(columns={'price':'賣價','size':'賣量'})
            if not b_df.empty or not a_df.empty:
                full_book = pd.concat([b_df, a_df], axis=1)
                book_ui.dataframe(full_book, hide_index=True, use_container_width=True)
            
            # B. 主力異動邏輯：對比上一秒掛單
            curr_b = {x['price']: x['size'] for x in snap.get('bids', [])}
            curr_a = {x['price']: x['size'] for x in snap.get('asks', [])}
            
            if st.session_state.last_book:
                lb = st.session_state.last_book
                # 監控賣盤壓力
                for p, s in curr_a.items():
                    if p in lb['a'] and abs(s - lb['a'][p]) >= alert_threshold:
                        mode = "🔴 壓力增加" if s > lb['a'][p] else "⚪ 壓力撤除"
                        st.session_state.alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {p} | {mode} {abs(s-lb['a'][p])}張")
                # 監控買盤支撐
                for p, s in curr_b.items():
                    if p in lb['b'] and abs(s - lb['b'][p]) >= alert_threshold:
                        mode = "🟢 支撐增加" if s > lb['b'][p] else "⚪ 支撐撤除"
                        st.session_state.alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {p} | {mode} {abs(s-lb['b'][p])}張")
            
            st.session_state.last_book = {'b': curr_b, 'a': curr_a}
            alert_ui.code("\n".join(st.session_state.alerts[:15]), language="bash")

            # C. 成交明細與多空分價
            lp, lv = snap.get('lastPrice'), snap.get('lastSize')
            if lp:
                # 明細更新
                st.session_state.trades.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {lp} | {lv}張")
                trade_ui.code("\n".join(st.session_state.trades[:50]), language="python")
                
                # 分價統計
                ps = str(lp)
                if ps not in st.session_state.stats: st.session_state.stats[ps] = {'B': 0, 'S': 0}
                b1 = snap.get('bids', [{}])[0].get('price', 0)
                if lp >= b1: st.session_state.stats[ps]['B'] += lv # 主動買進
                else: st.session_state.stats[ps]['S'] += lv        # 主動賣出
                
                # 繪圖
                df_stats = pd.DataFrame.from_dict(st.session_state.stats, orient='index').sort_index(ascending=False)
                chart_ui.bar_chart(df_stats, color=["#FF4B4B", "#00CC96"], height=250)
                
                # 力道顯示
                net = df_stats['B'].sum() - df_stats['S'].sum()
                force_ui.metric("多空淨力道 (Net Force)", f"{int(net)} 張", f"總成交 {int(df_stats['B'].sum() + df_stats['S'].sum())}")

    except Exception as e:
        # 即使發生錯誤也僅在背景處理，不毀掉畫面
        pass

    time.sleep(2)
    st.rerun()
