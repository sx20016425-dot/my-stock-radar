import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
import zoneinfo

import pandas as pd
import streamlit as st

try:
    from fugle_marketdata import WebSocketClient
except ImportError:
    WebSocketClient = None


TAIPEI_TZ = zoneinfo.ZoneInfo("Asia/Taipei")
DEFAULT_SYMBOLS = ["2330", "2317"]
MAX_RECENT_TRADES = 50


def now_taipei() -> datetime:
    return datetime.now(TAIPEI_TZ)


def format_fugle_time(value: Any) -> str:
    if value in (None, ""):
        return "-"

    try:
        timestamp = float(value)
        if timestamp > 10_000_000_000_000:
            timestamp /= 1_000_000
        elif timestamp > 10_000_000_000:
            timestamp /= 1_000
        return datetime.fromtimestamp(timestamp, TAIPEI_TZ).strftime("%H:%M:%S")
    except Exception:
        return str(value)


def normalize_symbols(raw: str) -> list[str]:
    parts = [item.strip() for item in raw.replace(";", ",").split(",")]
    return [item for item in parts if item]


def build_mock_snapshot(symbols: list[str]) -> dict[str, dict[str, Any]]:
    snapshots: dict[str, dict[str, Any]] = {}
    base_prices = {
        "2330": 812.0,
        "2317": 149.5,
        "0050": 193.2,
        "2454": 1220.0,
    }
    for idx, symbol in enumerate(symbols):
        base = base_prices.get(symbol, 100.0 + idx * 10)
        bids = [{"price": round(base - 0.5 - i * 0.5, 2), "size": 100 * (i + 1)} for i in range(5)]
        asks = [{"price": round(base + 0.5 + i * 0.5, 2), "size": 120 * (i + 1)} for i in range(5)]
        trades = deque(
            [
                {
                    "time": now_taipei().timestamp(),
                    "price": round(base + (i % 3 - 1) * 0.5, 2),
                    "size": 100 * (i + 1),
                    "bid": bids[0]["price"],
                    "ask": asks[0]["price"],
                    "volume": 1000 + i * 100,
                    "serial": i + 1,
                }
                for i in range(10)
            ],
            maxlen=MAX_RECENT_TRADES,
        )
        snapshots[symbol] = {
            "book": {"symbol": symbol, "bids": bids, "asks": asks, "time": now_taipei().timestamp()},
            "trades": trades,
            "last_trade": trades[-1],
        }
    return snapshots


@dataclass
class SymbolState:
    book: dict[str, Any] | None = None
    last_trade: dict[str, Any] | None = None
    trades: deque = field(default_factory=lambda: deque(maxlen=MAX_RECENT_TRADES))


class FugleRealtimeStore:
    def __init__(self, api_key: str | None):
        self.api_key = api_key
        self.lock = threading.Lock()
        self.states: dict[str, SymbolState] = defaultdict(SymbolState)
        self.subscriptions: set[tuple[str, str]] = set()
        self.started = False
        self.connected = False
        self.error_message: str | None = None
        self.last_event_at: datetime | None = None
        self.client = None
        self.stock = None

    def ensure_started(self) -> None:
        if self.started or not self.api_key or WebSocketClient is None:
            return

        self.started = True
        thread = threading.Thread(target=self._run, daemon=True)
        thread.start()

    def _run(self) -> None:
        try:
            self.client = WebSocketClient(api_key=self.api_key)
            self.stock = self.client.stock
            self.stock.on("connect", self._handle_connect)
            self.stock.on("disconnect", self._handle_disconnect)
            self.stock.on("error", self._handle_error)
            self.stock.on("message", self._handle_message)
            self.stock.connect()
        except Exception as exc:
            with self.lock:
                self.connected = False
                self.error_message = f"WebSocket 啟動失敗：{exc}"

    def _handle_connect(self) -> None:
        with self.lock:
            self.connected = True
            self.error_message = None

    def _handle_disconnect(self, code: Any, message: Any) -> None:
        with self.lock:
            self.connected = False
            self.error_message = f"連線中斷：{code} {message}"

    def _handle_error(self, error: Any) -> None:
        with self.lock:
            self.error_message = f"行情資料錯誤：{error}"

    def _handle_message(self, message: Any) -> None:
        payload = message
        if isinstance(message, str):
            try:
                import json

                payload = json.loads(message)
            except Exception:
                return

        event = payload.get("event")
        if event != "data":
            return

        channel = payload.get("channel")
        data = payload.get("data", {})
        symbol = data.get("symbol")
        if not symbol:
            return

        with self.lock:
            state = self.states[symbol]
            self.last_event_at = now_taipei()
            if channel == "books":
                state.book = data
            elif channel == "trades":
                state.last_trade = data
                state.trades.appendleft(data)

    def subscribe_symbols(self, symbols: list[str]) -> None:
        if not self.api_key or WebSocketClient is None:
            return

        self.ensure_started()
        wait_deadline = time.time() + 10
        while self.stock is None and time.time() < wait_deadline:
            time.sleep(0.1)

        if self.stock is None:
            with self.lock:
                if not self.error_message:
                    self.error_message = "WebSocket 連線逾時，尚未成功建立。"
            return

        for symbol in symbols:
            for channel in ("books", "trades"):
                key = (channel, symbol)
                if key in self.subscriptions:
                    continue
                self.stock.subscribe({"channel": channel, "symbol": symbol})
                self.subscriptions.add(key)

    def snapshot(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        with self.lock:
            result: dict[str, dict[str, Any]] = {}
            for symbol in symbols:
                state = self.states[symbol]
                result[symbol] = {
                    "book": state.book,
                    "last_trade": state.last_trade,
                    "trades": list(state.trades),
                }
            return result

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "connected": self.connected,
                "error_message": self.error_message,
                "last_event_at": self.last_event_at,
                "subscriptions": len(self.subscriptions),
            }


@st.cache_resource
def get_store(api_key: str | None) -> FugleRealtimeStore:
    store = FugleRealtimeStore(api_key)
    store.ensure_started()
    return store


def render_order_book(symbol: str, book: dict[str, Any] | None) -> None:
    st.subheader(f"{symbol} 五檔委買委賣")
    if not book:
        st.info("尚未收到五檔資料。")
        return

    bids = book.get("bids", [])
    asks = book.get("asks", [])
    rows = []
    for idx in range(max(len(bids), len(asks), 5)):
        bid = bids[idx] if idx < len(bids) else {}
        ask = asks[idx] if idx < len(asks) else {}
        rows.append(
            {
                "委買量": bid.get("size", ""),
                "委買價": bid.get("price", ""),
                "委賣價": ask.get("price", ""),
                "委賣量": ask.get("size", ""),
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(f"更新時間：{format_fugle_time(book.get('time'))}")


def render_trade_summary(symbol: str, trade: dict[str, Any] | None) -> None:
    st.subheader(f"{symbol} 最新成交")
    if not trade:
        st.info("尚未收到成交資料。")
        return

    cols = st.columns(4)
    cols[0].metric("成交價", trade.get("price", "-"))
    cols[1].metric("成交量", trade.get("size", "-"))
    cols[2].metric("累積量", trade.get("volume", "-"))
    cols[3].metric("時間", format_fugle_time(trade.get("time")))


def render_trade_tape(trades: list[dict[str, Any]]) -> None:
    st.subheader("即時成交明細")
    if not trades:
        st.info("尚未收到即時成交明細。")
        return

    trade_rows = list(trades)[:20]
    rows = [
        {
            "時間": format_fugle_time(item.get("time")),
            "成交價": item.get("price"),
            "成交量": item.get("size"),
            "買價": item.get("bid"),
            "賣價": item.get("ask"),
            "累積量": item.get("volume"),
            "序號": item.get("serial"),
        }
        for item in trade_rows
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def get_api_key() -> str | None:
    if "FUGLE_API_KEY" in st.secrets:
        return st.secrets["FUGLE_API_KEY"]
    return os.getenv("FUGLE_API_KEY")


st.set_page_config(page_title="台股即時監控台", page_icon=":bar_chart:", layout="wide")

st.title("台股即時監控台")
st.caption("使用 Streamlit 製作的台股五檔委買委賣與即時成交明細監控頁面。")

with st.sidebar:
    st.header("監控設定")
    symbols_raw = st.text_input("股票代碼", value=", ".join(DEFAULT_SYMBOLS), help="請用逗號分隔，例如：2330, 2317")
    symbols = normalize_symbols(symbols_raw) or DEFAULT_SYMBOLS
    refresh_seconds = st.slider("刷新秒數", min_value=1, max_value=10, value=1)
    st.caption("Fugle 免費方案有訂閱數限制，每個股票代碼會同時使用 books 與 trades 兩個頻道。")

api_key = get_api_key()
using_mock = not api_key or WebSocketClient is None

if using_mock:
    st.warning("目前為示範模式。請在 Streamlit secrets 設定 FUGLE_API_KEY 後切換為即時行情。")
    snapshots = build_mock_snapshot(symbols)
    status = {
        "connected": False,
        "error_message": None if WebSocketClient is not None else "尚未安裝 fugle-marketdata 套件。",
        "last_event_at": now_taipei(),
        "subscriptions": 0,
    }
else:
    store = get_store(api_key)
    store.subscribe_symbols(symbols)
    snapshots = store.snapshot(symbols)
    status = store.status()

status_cols = st.columns(4)
status_cols[0].metric("模式", "即時" if not using_mock else "示範")
status_cols[1].metric("連線", "已連線" if status["connected"] else "未連線")
status_cols[2].metric("訂閱數", status["subscriptions"])
status_cols[3].metric(
    "最後事件",
    status["last_event_at"].strftime("%H:%M:%S") if status["last_event_at"] else "-",
)

if status.get("error_message"):
    st.error(status["error_message"])


@st.fragment(run_every=refresh_seconds)
def live_dashboard() -> None:
    tabs = st.tabs(symbols)
    for tab, symbol in zip(tabs, symbols):
        with tab:
            if not using_mock:
                current_snapshots = store.snapshot([symbol])
                symbol_data = current_snapshots.get(symbol, {})
            else:
                symbol_data = snapshots.get(symbol, {})

            top_left, top_right = st.columns([1, 1])
            with top_left:
                render_order_book(symbol, symbol_data.get("book"))
            with top_right:
                render_trade_summary(symbol, symbol_data.get("last_trade"))
            render_trade_tape(symbol_data.get("trades", []))


live_dashboard()

with st.expander("部署說明"):
    st.markdown(
        """
        - 本系統使用官方 `fugle-marketdata` Python SDK 串接台股即時行情。
        - 原始碼可放在 GitHub，並由 Streamlit Community Cloud 直接部署。
        - 若你要對外公開此服務，請先確認行情資料的授權與使用規範是否符合需求。
        """
    )
