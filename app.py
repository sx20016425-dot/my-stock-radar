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
                self.error_message = f"WebSocket startup failed: {exc}"

    def _handle_connect(self) -> None:
        with self.lock:
            self.connected = True
            self.error_message = None

    def _handle_disconnect(self, code: Any, message: Any) -> None:
        with self.lock:
            self.connected = False
            self.error_message = f"Disconnected: {code} {message}"

    def _handle_error(self, error: Any) -> None:
        with self.lock:
            self.error_message = f"Market data error: {error}"

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
                    self.error_message = "WebSocket connection was not created in time."
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
    st.subheader(f"{symbol} Order Book")
    if not book:
        st.info("No order-book data yet.")
        return

    bids = book.get("bids", [])
    asks = book.get("asks", [])
    rows = []
    for idx in range(max(len(bids), len(asks), 5)):
        bid = bids[idx] if idx < len(bids) else {}
        ask = asks[idx] if idx < len(asks) else {}
        rows.append(
            {
                "Bid Size": bid.get("size", ""),
                "Bid Price": bid.get("price", ""),
                "Ask Price": ask.get("price", ""),
                "Ask Size": ask.get("size", ""),
            }
        )
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(f"Updated at: {format_fugle_time(book.get('time'))}")


def render_trade_summary(symbol: str, trade: dict[str, Any] | None) -> None:
    st.subheader(f"{symbol} Latest Trade")
    if not trade:
        st.info("No trade data yet.")
        return

    cols = st.columns(4)
    cols[0].metric("Price", trade.get("price", "-"))
    cols[1].metric("Size", trade.get("size", "-"))
    cols[2].metric("Volume", trade.get("volume", "-"))
    cols[3].metric("Time", format_fugle_time(trade.get("time")))


def render_trade_tape(trades: list[dict[str, Any]]) -> None:
    st.subheader("Trade Tape")
    if not trades:
        st.info("No recent trades yet.")
        return

    trade_rows = list(trades)[:20]
    rows = [
        {
            "Time": format_fugle_time(item.get("time")),
            "Price": item.get("price"),
            "Size": item.get("size"),
            "Bid": item.get("bid"),
            "Ask": item.get("ask"),
            "Volume": item.get("volume"),
            "Serial": item.get("serial"),
        }
        for item in trade_rows
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def get_api_key() -> str | None:
    if "FUGLE_API_KEY" in st.secrets:
        return st.secrets["FUGLE_API_KEY"]
    return os.getenv("FUGLE_API_KEY")


st.set_page_config(page_title="TW Stock Live Dashboard", page_icon=":bar_chart:", layout="wide")

st.title("TW Stock Live Dashboard")
st.caption("A Streamlit dashboard for Taiwan stock five-level order book and live trade details.")

with st.sidebar:
    st.header("Settings")
    symbols_raw = st.text_input("Symbols", value=", ".join(DEFAULT_SYMBOLS), help="Comma-separated, for example: 2330, 2317")
    symbols = normalize_symbols(symbols_raw) or DEFAULT_SYMBOLS
    refresh_seconds = st.slider("Refresh every (sec)", min_value=1, max_value=10, value=1)
    st.caption("Fugle free plans have subscription limits. Each symbol uses both books and trades channels.")

api_key = get_api_key()
using_mock = not api_key or WebSocketClient is None

if using_mock:
    st.warning("Running in demo mode. Add FUGLE_API_KEY to Streamlit secrets to switch to live market data.")
    snapshots = build_mock_snapshot(symbols)
    status = {
        "connected": False,
        "error_message": None if WebSocketClient is not None else "fugle-marketdata is not installed.",
        "last_event_at": now_taipei(),
        "subscriptions": 0,
    }
else:
    store = get_store(api_key)
    store.subscribe_symbols(symbols)
    snapshots = store.snapshot(symbols)
    status = store.status()

status_cols = st.columns(4)
status_cols[0].metric("Mode", "Live" if not using_mock else "Demo")
status_cols[1].metric("Connection", "Connected" if status["connected"] else "Disconnected")
status_cols[2].metric("Subscriptions", status["subscriptions"])
status_cols[3].metric(
    "Last Event",
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

with st.expander("Deployment Notes"):
    st.markdown(
        """
        - This app uses the official `fugle-marketdata` Python SDK for live Taiwan stock data.
        - GitHub is used for source control, and Streamlit Community Cloud can deploy directly from the repo.
        - If you plan to share this publicly, confirm that your market-data usage is compliant with the vendor's license terms.
        """
    )
