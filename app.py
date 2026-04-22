import streamlit as st
import pandas as pd
import datetime
import time
import requests
import yfinance as yf

# --- 1. 專業介面配置 (這部分決定了專業度) ---
st.set_page_config(page_title="Alpha-Trader Terminal v7.0", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
    .main { background-color: #0D1117; }
    .stMetric { background: #161B22; padding: 15px; border-radius: 10px; border: 1px solid #30363D; }
    [data-testid="stMetricValue"] { font-size: 26px !important; color: #58A6FF !important; }
    .stCodeBlock { border: 1px solid #30363D !important; background-color: #010409 !important; min-height: 250px !important; }
    h3 { color: #8B949E; font-size: 14px !important; font-weight: 600; border-left: 3px solid #58A6FF; padding-left: 8px; margin-top: 10px; }
    .stDataFrame { border: 1px solid #30363D !important; border-radius: 5px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. 狀態持久化 (核心資產) ---
API_KEY = "MWI2Y2NlMTYtZmNjNy00NGJmLWFkMTYtNDVjZjk2MjJkNzFhIDA1YTliNzZhLWI0NzItNGYxMS1iYTIxLWYyN2ZkNjgzNzI5YQ=="

# 初始化所有會話狀態，確保不會報錯
if 'mkt_cache' not in st.session_state:
    st.session_state.mkt_cache = {k: {"p": "--", "pct": "0.00"} for k in ["台指期", "加權指數", "TSM(ADR)", "日經 225", "標普 500"]}
if 'trade_history' not in st.session_state: st.session_state.trade_history = ["--- 等待首筆成交 ---"]
if 'order_alerts' not in st.session_state: st.session_state.order_alerts = ["--- 監控系統已啟動 ---"]
if 'price_stats' not in st.session_state: st.session_state.price_stats = {}
if 'last_books' not in st.session_state: st.session_state.last_books = None

# --- 3. 數據同步函式 (完全獨立) ---

def sync_top_indices():
    headers = {"X-API-KEY": API_KEY}
    # 1. 台指期 (TXFR)
    try:
        r = requests.get("https://api.fugle.tw/marketdata/v1.0/futures/snapshot/quotes/TXFR", headers=headers, timeout=2)
        if r.status_code == 200:
            d = r.json()
            st.session_state.mkt_cache["台指期"] = {"p": f"{d.get('lastPrice', 0):.0f}", "pct": f"{d.get('changePercent', 0):.2f}"}
    except: pass
    # 2. 加權指數 (IX0001)
    try:
        r = requests.get("https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/IX0001", headers=headers, timeout=2)
        if r.status_code == 200:
            d = r.json()
            st.session_state.mkt_cache["加權指數"] = {"p": f"{d.get('lastPrice', 0):.0f}", "pct": f"{d.get('changePercent', 0):.2f}"}
    except: pass
    # 3. Yahoo 全球 (TSM/N225/GSPC)
    targets = {"TSM(ADR)": "TSM", "日經 225": "^N225", "標普 500": "^GSPC"}
    for label, sym in targets.items():
        try:
            t = yf.Ticker(sym); df = t.history(period="1d")
            if not df.empty:
                p = df['Close'].iloc[-1]; pct = ((p - t.info.get('previousClose', p)) / t.info.get('previousClose', 1)) * 100
                st.session_state.mkt_cache[label] = {"p": f"{p:.2f}" if "ADR" in label else f"{p:.0f}", "pct": f"{pct:.2f}"}
        except: pass

# --- 4. 靜態畫面建構 (這部分決定功能是否消失) ---

st.markdown("## 🏛️ Alpha-Trader <span style='color:#58A6FF'>Professional Terminal v7.0</span>", unsafe_allow_html=True)

# 指數欄位 (固定 5 欄)
sync_top_indices()
m_cols = st.columns(5)
for i, label in enumerate(["台指期", "加權指數", "TSM(ADR)", "日經 225", "標普 500"]):
    m_cols[i].metric(label, st.session_state.mkt_cache[label]["p"], f"{st.session_state.mkt_cache[label]['pct']}%")

st.divider()

# 側邊設定
with st.sidebar:
    st.header("⚙️ 設定")
    stock_no = st.text_input("個股代號", value="2330").upper()
    run_live = st.toggle("啟動監控", value=True)
    qty_limit = st.number_input("大單閾值", value=50)
    if st.button("數據重置"):
        st.session_state.trade_history = []; st.session_state.order_alerts = []; st.session_state.price_stats = {}; st.rerun()

# --- 核心佈局 (Placeholder 必須在邏輯外定義) ---
main_l, main_r = st.columns([2.2, 0.8])

with main_l:
    # 第一排：五檔與主力 (框架)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("<h3>🏛️ 五檔報價 (Level 2)</h3>", unsafe_allow_html=True)
        book_ui = st.empty()
    with c2:
        st.markdown("<h3>🚨 大單異動紀錄</h3>", unsafe_allow_html=True)
        alert_ui = st.empty()
    
    # 第二排：分價統計
    st.markdown("<h3>📊 多空分價量能</h3>", unsafe_allow_html=True)
    chart_ui = st.empty()
    force_ui = st.empty()

with main_r:
    st.markdown("<h3>🔔 即時成交明細</h3>", unsafe_allow_html=True)
    trade_ui = st.empty()

# --- 5. 數據填充邏輯 ---

if run_live:
    try:
        r = requests.get(f"https://api.fugle.tw/marketdata/v1.0/stock/snapshot/quotes/{stock_no}", 
                         headers={"X-API-KEY": API_KEY}, timeout=2)
        if r.status_code == 200:
            snap = r.json()
            
            # A. 五檔填充 (買價/買量/賣價/賣量)
            b_df = pd.DataFrame(snap.get('bids', [])).rename(columns={'price':'買價','size':'買量'})
            a_df = pd.DataFrame(snap.get('asks', [])).rename(columns={'price':'賣價','size':'賣量'})
            book_ui.dataframe(pd.concat([b_df, a_df], axis=1), hide_index=True, use_container_width=True)
            
            # B. 主力異動監控
            curr_b = {x['price']: x['size'] for x in snap.get('bids', [])}
            curr_a = {x['price']: x['size'] for x in snap.get('asks', [])}
            if st.session_state.last_books:
                old_b, old_a = st.session_state.last_books['b'], st.session_state.last_books['a']
                for p, s in curr_a.items():
                    if p in old_a and abs(s - old_a[p]) >= qty_limit:
                        tag = "🔴 壓單增加" if s > old_a[p] else "⚪ 壓力撤除"
                        st.session_state.order_alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {p} | {tag} {abs(s-old_a[p])}")
                for p, s in curr_b.items():
                    if p in old_b and abs(s - old_b[p]) >= qty_limit:
                        tag = "🟢 支撐增加" if s > old_b[p] else "⚪ 支撐撤除"
                        st.session_state.order_alerts.insert(0, f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {p} | {tag} {abs(s-old_b[p])}")
            st.session_state.last_books = {'b': curr_b, 'a': curr_a}
            alert_ui.code("\n".join(st.session_state.order_alerts[:15]), language="bash")
            
            # C. 明細與分價
            lp, lv = snap.get('lastPrice'), snap.get('lastSize')
            if lp:
                st.session_state.trade_history.insert(0, f"{datetime.datetime.now().strftime('%H:%M:%S')} | 價 {lp} | 量 {lv}")
                # 統計力道
                ps = str(lp)
                if ps not in st.session_state.price_stats: st.session_state.price_stats[ps] = {'B': 0, 'S': 0}
                b1 = snap.get('bids', [{}])[0].get('price', 0)
                if lp >= b1: st.session_state.price_stats[ps]['B'] += lv
                else: st.session_state.price_stats[ps]['S'] += lv
            
            trade_ui.code("\n".join(st.session_state.trade_history[:45]), language="python")
            
            if st.session_state.price_stats:
                df_p = pd.DataFrame.from_dict(st.session_state.price_stats, orient='index').sort_index(ascending=False)
                chart_ui.bar_chart(df_p, color=["#FF4B4B", "#00CC96"], height=250)
                tb, ts = df_p['B'].sum(), df_p['S'].sum()
                force_ui.metric("多空淨力道 (NET FORCE)", f"{int(tb-ts)} 張", f"累積: {int(tb+ts)}")
        else:
            # 如果 API 失敗，也要讓 UI 顯示「請求失敗」
            alert_ui.warning("API 請求頻率過高或未開盤")

    except Exception as e:
        alert_ui.error(f"連線異常: {e}")

    time.sleep(2)
    st.rerun()
