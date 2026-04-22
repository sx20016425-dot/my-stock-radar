import streamlit as st
import pandas as pd
import datetime
import time
import requests
import yfinance as yf
import plotly.graph_objects as go

# --- 1. 配置與專業樣式注入 ---
st.set_page_config(page_title="專業操盤戰情室 v3.0", layout="wide", initial_sidebar_state="expanded")

# 專業黑標質感 CSS
st.markdown("""
    <style>
    .main { background-color: #0D1117; }
    .stMetric { background: #161B22; padding: 15px; border-radius: 10px; border: 1px solid #30363D; }
    [data-testid="stMetricValue"] { font-size: 26px !important; color: #58A6FF !important; }
    .stCodeBlock { border: 1px solid #30363D !important; background-color: #010409 !important; }
    h3 { color: #C9D1D9; font-size: 15px !important; font-weight: 600; letter-spacing: 1px; margin-bottom: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 核心初始化 ---
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

# 狀態持久化
state_list = {
    'price_stats': {},        # 分價統計
    'trade_history': [],      # 成交明細
    'order_alerts': [],       # 主力警示
    'last_books_raw': None,   # 五檔對比快照
    'mkt_cache': {k: {"p": "--", "pct": "0.00"} for k in ["台指期", "加權指數", "TSM(ADR)", "日經 225", "標普 500"]}
}
for key, val in state_list.items():
    if key not in st.session_state: st.session_state[key] = val

# --- 3. 數據引擎：修復台指期價格核心 ---

def fetch_txf_futures():
    """專門抓取富果期貨 API 的台指期數據"""
    # TXFR 是富果提供的近月連續合約代號
    url = "https://api.fugle.tw/marketdata/v1.0/futures/snapshot/quotes/TXFR"
    try:
        resp = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=3)
        if resp.status_code == 200:
            d = resp.json()
            return {
                "p": d.get('lastPrice', "--"),
                "pct": d.get('changePercent', 0.00)
            }
    except: return None

def fetch_tse_index():
    """抓取加權指數 (IX0001)"""
    url = "https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/IX0001"
    try:
        resp = requests.get(url, headers={"X-API-KEY": API_KEY}, timeout=3)
        if resp.status_code == 200:
            d = resp.json()
            return {
                "p": d.get('lastPrice', "--"),
                "pct": d.get('changePercent', 0.00)
            }
    except: return None

def get_global_indices():
    """抓取全球指標 (Yahoo Finance)"""
    targets = {"TSM(ADR)": "TSM", "日經 225": "^N225", "標普 500": "^GSPC"}
    results = {}
    for label, sym in targets.items():
        try:
            t = yf.Ticker(sym); df = t.history(period="1d")
            if not df.empty:
                p = df['Close'].iloc[-1]
                prev = t.info.get('previousClose', p)
                pct = ((p - prev) / prev) * 100
                results[label] = {"p": f"{p:.2f}" if "ADR" in label or "500" in label else f"{p:.0f}", "pct": f"{pct:.2f}"}
        except: results[label] = {"p": "--", "pct": "0.00"}
    return results

# --- 4. 介面與監控邏輯 ---

st.title("🏛️ Alpha-Trader Premium Terminal")

# A. 頂部看板更新
with st.spinner("同步全球金融數據..."):
    txf_data = fetch_txf_futures()
    tse_data = fetch_tse_index()
    global_data = get_global_indices()
    
    if txf_data: st.session_state.mkt_cache["台指期"] = {"p": f"{txf_data['p']}", "pct": f"{txf_data['pct']:.2f}"}
    if tse_data: st.session_state.mkt_cache["加權指數"] = {"p": f"{tse_data['p']}", "pct": f"{tse_data['pct']:.2f}"}
    for k, v in global_data.items(): st.session_state.mkt_cache[k] = v

idx_row = st.columns(5)
for i, label in enumerate(["台指期", "加權指數", "TSM(ADR)", "日經 225", "標普 500"]):
    with idx_row[i]:
        st.metric(label, st.session_state.mkt_cache[label]["p"], f"{st.session_state.mkt_cache[label]['pct']}%")

st.divider()

# B. 控制面板
with st.sidebar:
    st.header("🎛️ 戰情設定")
    target_stock = st.text_input("監控標的 (個股)", value="2330").upper()
    monitor_switch = st.toggle("啟動高頻輪詢系統", value=True)
    alert_threshold = st.number_input("主力大單閾值 (張)", value=50)
    st.divider()
    if st.button("🗑️ 清除所有會計數據", use_container_width=True):
        st.session_state.price_stats = {}; st.session_state.trade_history = []; st.session_state.order_alerts = []; st.session_state.last_books_raw = None
        st.rerun()
    st.info(f"最後更新: {datetime.datetime.now().strftime('%H:%M:%S')}")

# C. 主版面佈局 (三大功能區)
col_main_left, col_main_right = st.columns([2.2, 0.8])

with col_main_left:
    # 第一區：五檔與主力分析
    u1, u2 = st.columns(2)
    with u1:
        st.subheader("🏛️ LEVEL 2 ORDER BOOK")
        book_ui = st.empty()
    with u2:
        st.subheader("🚨 INSTITUTIONAL ORDER FLOW")
        alert_ui = st.empty()
    
    # 第二區：分價圖與多空淨值
    st.subheader("📊 PRICE-VOLUME PROFILE & MARKET FORCE")
    chart_ui = st.empty()
    force_ui = st.empty()
    force_desc = st.empty()

with col_main_right:
    st.subheader("🔔 REAL-TIME TIME & SALES")
    trade_ui = st.empty()

# --- 5. 高頻監控循環 ---

if monitor_switch:
    stock_url = f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{target_stock}"
    try:
        resp = requests.get(stock_url, headers={"X-API-KEY": API_KEY}, timeout=2)
        if resp.status_code == 200:
            snap = resp.json()
            
            # 1. 五檔異動比對邏輯 (關鍵核心)
            bids = {x['price']: x['size'] for x in snap.get('bids', [])}
            asks = {x['price']: x['size'] for x in snap.get('asks', [])}
            
            if st.session_state.last_books_raw:
                old_b, old_a = st.session_state.last_books_raw['b'], st.session_state.last_books_raw['a']
                # 壓力位分析
                for p, s in asks.items():
                    if p in old_a:
                        diff = s - old_a[p]
                        if abs(diff) >= alert_threshold:
                            tag = "🔴 壓單增加" if diff > 0 else "⚪ 壓力撤除"
                            st.session_state.order_alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {p} | {tag} {abs(diff)}張")
                # 支撐位分析
                for p, s in bids.items():
                    if p in old_b:
                        diff = s - old_b[p]
                        if abs(diff) >= alert_threshold:
                            tag = "🟢 支撐增加" if diff > 0 else "⚪ 支撐撤除"
                            st.session_state.order_alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {p} | {tag} {abs(diff)}張")
            st.session_state.last_books_raw = {'b': bids, 'a': asks}

            # 2. 多空力道統計分析
            lp, lv = snap.get('lastPrice'), snap.get('lastSize')
            if lp:
                ps = str(lp); b1 = snap.get('bids', [{}])[0].get('price', 0)
                if ps not in st.session_state.price_stats: st.session_state.price_stats[ps] = {'多方主動': 0, '空方主動': 0}
                if lp >= b1: st.session_state.price_stats[ps]['多方主動'] += lv
                else: st.session_state.price_stats[ps]['空方主動'] += lv
                st.session_state.trade_history.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | {lp} | {lv}張")

            # 3. 渲染所有功能 UI
            # 五檔表格
            b_df = pd.DataFrame(snap.get('bids', [])).rename(columns={'price':'買價','size':'買量'})
            a_df = pd.DataFrame(snap.get('asks', [])).rename(columns={'price':'賣價','size':'賣量'})
            book_ui.dataframe(pd.concat([b_df, a_df], axis=1), hide_index=True, use_container_width=True)
            
            # 主力警示日誌
            alert_ui.code("\n".join(st.session_state.order_alerts[:14]), language="bash")
            
            # 分價圖 (使用自定義顏色)
            if st.session_state.price_stats:
                df = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index').sort_index(ascending=False)
                chart_ui.bar_chart(df, color=["#FF4B4B", "#00CC96"], height=250)
                
                # 多空淨額計算
                t_buy, t_sell = df['多方主動'].sum(), df['空方主動'].sum()
                net_force = t_buy - t_sell
                force_ui.metric("市場多空淨力道 (NET FORCE)", f"{int(net_force)} 張", f"買入 {int(t_buy)} / 賣出 {int(t_sell)}")
                force_desc.write(f"💡 目前{'多方' if net_force > 0 else '空方'}力道較強，代表{'內盤吃貨' if net_force > 0 else '外盤拋售'}行為顯著。")

            # 成交明細
            trade_ui.code("\n".join(st.session_state.trade_history[:50]), language="python")

    except Exception as e:
        st.error(f"系統輪詢異常: {e}")
    
    time.sleep(2)
    st.rerun()
