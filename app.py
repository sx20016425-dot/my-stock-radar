import base64
import binascii
import os
import re
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
    from fugle_marketdata import RestClient, WebSocketClient
except ImportError:
    RestClient = None
    WebSocketClient = None

try:
    import yfinance as yf
except ImportError:
    yf = None


TAIPEI_TZ = zoneinfo.ZoneInfo("Asia/Taipei")
DEFAULT_SYMBOLS = ["2330", "2317"]
MAX_RECENT_TRADES = 50
MAX_BOOK_HISTORY = 240
MAX_SIGNAL_EVENTS = 80
UUID_PAIR_PATTERN = re.compile(r"^[0-9a-fA-F-]{36}\s+[0-9a-fA-F-]{36}$")
BENCHMARK_SYMBOLS = [
    {"label": "台灣加權指數", "symbol": "^TWII", "note": "現貨指數參考"},
    {"label": "日經225", "symbol": "^N225", "note": "現貨指數參考"},
    {"label": "恆生指數", "symbol": "^HSI", "note": "現貨指數參考"},
    {"label": "韓國KOSPI", "symbol": "^KS11", "note": "現貨指數參考"},
    {"label": "那指期貨參考", "symbol": "NQ=F", "note": "期貨參考"},
    {"label": "標普期貨參考", "symbol": "ES=F", "note": "期貨參考"},
]


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


def format_benchmark_time(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        ts = value if isinstance(value, pd.Timestamp) else pd.Timestamp(value)
        if ts.tzinfo is None:
            return ts.strftime("%H:%M")
        return ts.tz_convert(TAIPEI_TZ).strftime("%H:%M")
    except Exception:
        return "-"


def normalize_symbols(raw: str) -> list[str]:
    parts = [item.strip() for item in raw.replace(";", ",").replace("，", ",").split(",")]
    return [item for item in parts if item]


def mask_secret(value: str | None) -> str:
    if not value:
        return "未提供"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def normalize_fugle_api_key(raw_key: str | None) -> tuple[str | None, str]:
    if not raw_key:
        return None, "未提供 API key"

    raw_key = raw_key.strip()
    try:
        decoded = base64.b64decode(raw_key, validate=True).decode("utf-8").strip()
    except (binascii.Error, UnicodeDecodeError):
        return raw_key, "使用原始 API key"

    if UUID_PAIR_PATTERN.match(decoded):
        return decoded, "偵測到 Base64 包裝格式，已自動解碼後使用"

    return raw_key, "使用原始 API key"


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
                    "time": now_taipei().timestamp() - (9 - i),
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
            "last_trade": trades[0],
        }
    return snapshots


@st.cache_data(ttl=15, show_spinner=False)
def test_rest_quote(api_key: str, symbol: str) -> dict[str, Any]:
    if RestClient is None:
        return {
            "ok": False,
            "message": "RestClient 不可用，fugle-marketdata 套件可能未正確安裝。",
            "data": None,
        }

    try:
        client = RestClient(api_key=api_key)
        quote = client.stock.intraday.quote(symbol=symbol)
        return {
            "ok": True,
            "message": f"REST 測試成功：已取得 {symbol} 報價。",
            "data": quote,
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": f"REST 測試失敗：{exc}",
            "data": None,
        }


@st.cache_data(ttl=30, show_spinner=False)
def fetch_benchmark_data() -> dict[str, Any]:
    if yf is None:
        return {
            "ok": False,
            "message": "yfinance 套件未安裝，無法載入全球指數參考。",
            "items": [],
        }

    items: list[dict[str, Any]] = []
    failures: list[str] = []

    for config in BENCHMARK_SYMBOLS:
        label = config["label"]
        symbol = config["symbol"]
        note = config["note"]
        try:
            ticker = yf.Ticker(symbol)
            history = ticker.history(period="2d", interval="1m", auto_adjust=False, prepost=True)
            if history.empty:
                history = ticker.history(period="5d", interval="1d", auto_adjust=False)

            close_series = history["Close"].dropna()
            if close_series.empty:
                raise ValueError("查無價格資料")

            last_price = float(close_series.iloc[-1])
            previous_close = None
            fast_info = getattr(ticker, "fast_info", None)
            if fast_info:
                previous_close = fast_info.get("previousClose") or fast_info.get("previous_close")

            if previous_close in (None, 0):
                previous_close = float(close_series.iloc[-2]) if len(close_series) >= 2 else last_price

            change = last_price - float(previous_close)
            change_pct = 0.0 if previous_close == 0 else (change / float(previous_close)) * 100
            timestamp = close_series.index[-1]

            items.append(
                {
                    "label": label,
                    "symbol": symbol,
                    "note": note,
                    "price": round(last_price, 2),
                    "change": round(change, 2),
                    "change_pct": round(change_pct, 2),
                    "time": format_benchmark_time(timestamp),
                }
            )
        except Exception as exc:
            failures.append(f"{label}: {exc}")
            items.append(
                {
                    "label": label,
                    "symbol": symbol,
                    "note": note,
                    "price": None,
                    "change": None,
                    "change_pct": None,
                    "time": "-",
                }
            )

    message = "全球指數參考載入成功。"
    if failures:
        message = "部分全球指數參考載入失敗：" + " | ".join(failures[:3])

    return {
        "ok": len(failures) < len(BENCHMARK_SYMBOLS),
        "message": message,
        "items": items,
    }


def book_totals(levels: list[dict[str, Any]]) -> tuple[float, int]:
    total_size = sum(int(level.get("size", 0) or 0) for level in levels[:5])
    near3_size = sum(int(level.get("size", 0) or 0) for level in levels[:3])
    return float(total_size), int(near3_size)


def book_level_map(levels: list[dict[str, Any]]) -> dict[float, int]:
    result: dict[float, int] = {}
    for level in levels[:5]:
        price = level.get("price")
        size = level.get("size")
        if price in (None, ""):
            continue
        result[float(price)] = int(size or 0)
    return result


def summarise_book(book: dict[str, Any] | None) -> dict[str, Any] | None:
    if not book:
        return None

    bids = book.get("bids", [])
    asks = book.get("asks", [])
    bid_total, bid_near3 = book_totals(bids)
    ask_total, ask_near3 = book_totals(asks)

    return {
        "time": float(book.get("time") or now_taipei().timestamp()),
        "bid_total": bid_total,
        "ask_total": ask_total,
        "bid_near3_ratio": 0.0 if bid_total == 0 else bid_near3 / bid_total,
        "ask_near3_ratio": 0.0 if ask_total == 0 else ask_near3 / ask_total,
        "best_bid": float(bids[0]["price"]) if bids else None,
        "best_ask": float(asks[0]["price"]) if asks else None,
        "bid_map": book_level_map(bids),
        "ask_map": book_level_map(asks),
    }


def classify_severity(score: float) -> str:
    if score >= 0.85:
        return "高"
    if score >= 0.6:
        return "中"
    return "低"


def score_to_bias(score: float) -> str:
    if score >= 1.4:
        return "偏多"
    if score <= -1.4:
        return "偏空"
    return "中性"


@dataclass
class SignalEvent:
    event_type: str
    side: str
    message: str
    score: float
    created_at: datetime = field(default_factory=now_taipei)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SymbolState:
    book: dict[str, Any] | None = None
    last_trade: dict[str, Any] | None = None
    trades: deque = field(default_factory=lambda: deque(maxlen=MAX_RECENT_TRADES))
    book_history: deque = field(default_factory=lambda: deque(maxlen=MAX_BOOK_HISTORY))
    trade_history: deque = field(default_factory=lambda: deque(maxlen=MAX_BOOK_HISTORY))
    signal_events: deque = field(default_factory=lambda: deque(maxlen=MAX_SIGNAL_EVENTS))
    signal_cooldowns: dict[str, float] = field(default_factory=dict)
    last_processed_trade_serial: Any = None
    open_trade: dict[str, Any] | None = None
    session_high: float | None = None
    session_low: float | None = None


class FugleRealtimeStore:
    def __init__(self, api_key: str | None):
        self.api_key = api_key
        self.lock = threading.Lock()
        self.connection_ready = threading.Event()
        self.auth_ready = threading.Event()
        self.states: dict[str, SymbolState] = defaultdict(SymbolState)
        self.subscriptions: set[tuple[str, str]] = set()
        self.pending_subscriptions: set[tuple[str, str]] = set()
        self.started = False
        self.connected = False
        self.authenticated = False
        self.error_message: str | None = None
        self.last_event_at: datetime | None = None
        self.last_status_message: str | None = None
        self.client = None
        self.stock = None

    def ensure_started(self) -> None:
        if self.started or not self.api_key or WebSocketClient is None:
            return
        self.started = True
        threading.Thread(target=self._run, daemon=True).start()

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
                self.authenticated = False
                self.error_message = f"WebSocket 啟動失敗：{exc}"
                self.last_status_message = "WebSocket 啟動例外"
            self.connection_ready.clear()
            self.auth_ready.clear()

    def _handle_connect(self) -> None:
        with self.lock:
            self.connected = True
            self.last_status_message = "WebSocket 已建立，等待驗證"
            if self.error_message == "正在建立 WebSocket 連線，請稍候。":
                self.error_message = None
        self.connection_ready.set()

    def _handle_disconnect(self, code: Any, message: Any) -> None:
        with self.lock:
            self.connected = False
            self.authenticated = False
            self.error_message = f"連線中斷：{code} {message}"
            self.last_status_message = "WebSocket 已中斷"
        self.connection_ready.clear()
        self.auth_ready.clear()

    def _handle_error(self, error: Any) -> None:
        with self.lock:
            self.error_message = f"行情資料錯誤：{error}"
            self.last_status_message = "收到 error 事件"

    def _emit_signal(
        self,
        state: SymbolState,
        event_type: str,
        side: str,
        message: str,
        score: float,
        extra: dict[str, Any] | None = None,
        cooldown_seconds: int = 8,
    ) -> None:
        now_ts = now_taipei().timestamp()
        cooldown_key = f"{event_type}:{side}"
        if now_ts - state.signal_cooldowns.get(cooldown_key, 0) < cooldown_seconds:
            return
        state.signal_cooldowns[cooldown_key] = now_ts
        state.signal_events.appendleft(
            SignalEvent(
                event_type=event_type,
                side=side,
                message=message,
                score=score,
                extra=extra or {},
            )
        )

    def _analyse_order_book_change(self, symbol: str, state: SymbolState, current_trade: dict[str, Any] | None = None) -> None:
        if len(state.book_history) < 2:
            return

        prev = state.book_history[-2]
        curr = state.book_history[-1]

        bid_delta = curr["bid_total"] - prev["bid_total"]
        ask_delta = curr["ask_total"] - prev["ask_total"]

        if prev["bid_total"] > 0:
            if curr["bid_total"] >= prev["bid_total"] * 1.6 and bid_delta >= 500:
                score = min(0.95, 0.55 + abs(bid_delta) / max(prev["bid_total"], 1))
                self._emit_signal(
                    state,
                    "bid_stack_up",
                    "買盤",
                    f"{symbol} 買盤五檔總量異常增加 {int(bid_delta):,}，疑似堆量或承接。",
                    score,
                    {"bid_delta": bid_delta},
                )
            if curr["bid_total"] <= prev["bid_total"] * 0.55 and abs(bid_delta) >= 500:
                score = min(0.95, 0.55 + abs(bid_delta) / max(prev["bid_total"], 1))
                self._emit_signal(
                    state,
                    "bid_pull",
                    "買盤",
                    f"{symbol} 買盤五檔總量快速減少 {int(abs(bid_delta)):,}，疑似抽單。",
                    score,
                    {"bid_delta": bid_delta},
                )

        if prev["ask_total"] > 0:
            if curr["ask_total"] >= prev["ask_total"] * 1.6 and ask_delta >= 500:
                score = min(0.95, 0.55 + abs(ask_delta) / max(prev["ask_total"], 1))
                self._emit_signal(
                    state,
                    "ask_stack_up",
                    "賣盤",
                    f"{symbol} 賣盤五檔總量異常增加 {int(ask_delta):,}，疑似壓盤掛單。",
                    score,
                    {"ask_delta": ask_delta},
                )
            if curr["ask_total"] <= prev["ask_total"] * 0.55 and abs(ask_delta) >= 500:
                score = min(0.95, 0.55 + abs(ask_delta) / max(prev["ask_total"], 1))
                self._emit_signal(
                    state,
                    "ask_pull",
                    "賣盤",
                    f"{symbol} 賣盤五檔總量快速減少 {int(abs(ask_delta)):,}，疑似抽單。",
                    score,
                    {"ask_delta": ask_delta},
                )

        bid_ratio_jump = curr["bid_near3_ratio"] - prev["bid_near3_ratio"]
        ask_ratio_jump = curr["ask_near3_ratio"] - prev["ask_near3_ratio"]

        if bid_ratio_jump >= 0.18 and curr["bid_near3_ratio"] >= 0.62:
            self._emit_signal(
                state,
                "bid_front_loaded",
                "買盤",
                f"{symbol} 買盤前三檔占比提高到 {curr['bid_near3_ratio']:.0%}，近價承接明顯集中。",
                min(0.9, 0.45 + bid_ratio_jump * 2),
                {"bid_near3_ratio": curr["bid_near3_ratio"]},
            )

        if ask_ratio_jump >= 0.18 and curr["ask_near3_ratio"] >= 0.62:
            self._emit_signal(
                state,
                "ask_front_loaded",
                "賣盤",
                f"{symbol} 賣盤前三檔占比提高到 {curr['ask_near3_ratio']:.0%}，近價賣壓集中。",
                min(0.9, 0.45 + ask_ratio_jump * 2),
                {"ask_near3_ratio": curr["ask_near3_ratio"]},
            )

        if current_trade is None:
            return

        trade_price = float(current_trade.get("price") or 0)
        trade_size = int(current_trade.get("size") or 0)
        if trade_price <= 0 or trade_size <= 0:
            return

        prev_best_bid = prev["best_bid"]
        prev_best_ask = prev["best_ask"]

        if prev_best_ask is not None and trade_price >= prev_best_ask:
            prev_size = prev["ask_map"].get(trade_price)
            curr_size = curr["ask_map"].get(trade_price)
            if prev_size is not None and curr_size is not None and curr_size >= prev_size:
                self._emit_signal(
                    state,
                    "ask_replenish_after_trade",
                    "賣盤",
                    f"{symbol} 成交價 {trade_price:.2f} 成交後，賣盤同價位未減反增，疑似補單。",
                    0.78,
                    {"price": trade_price, "trade_size": trade_size},
                )

        if prev_best_bid is not None and trade_price <= prev_best_bid:
            prev_size = prev["bid_map"].get(trade_price)
            curr_size = curr["bid_map"].get(trade_price)
            if prev_size is not None and curr_size is not None and curr_size >= prev_size:
                self._emit_signal(
                    state,
                    "bid_replenish_after_trade",
                    "買盤",
                    f"{symbol} 成交價 {trade_price:.2f} 成交後，買盤同價位未減反增，疑似補單。",
                    0.78,
                    {"price": trade_price, "trade_size": trade_size},
                )

    def _update_opening_state(self, symbol: str, state: SymbolState, trade: dict[str, Any]) -> None:
        trade_price = float(trade.get("price") or 0)
        if trade_price <= 0:
            return

        if state.open_trade is None:
            state.open_trade = trade
            self._emit_signal(
                state,
                "opening_trade",
                "開盤",
                f"{symbol} 已記錄第一筆開盤成交，價格 {trade_price:.2f}。",
                0.5,
                {"open_price": trade_price},
                cooldown_seconds=3600,
            )

        state.session_high = trade_price if state.session_high is None else max(state.session_high, trade_price)
        state.session_low = trade_price if state.session_low is None else min(state.session_low, trade_price)

    def _handle_message(self, message: Any) -> None:
        payload = message
        if isinstance(message, str):
            try:
                import json
                payload = json.loads(message)
            except Exception:
                return

        event = payload.get("event")

        if event == "authenticated":
            with self.lock:
                self.authenticated = True
                self.error_message = None
                self.last_status_message = "API key 驗證成功"
            self.auth_ready.set()
            self._flush_pending_subscriptions()
            return

        if event == "heartbeat":
            with self.lock:
                self.last_event_at = now_taipei()
                self.last_status_message = "收到 heartbeat"
            return

        if event == "error":
            error_data = payload.get("data", {})
            error_message = error_data.get("message") or str(error_data) or "未知錯誤"
            with self.lock:
                self.error_message = f"Fugle 驗證或訂閱錯誤：{error_message}"
                self.last_status_message = "收到 error 事件"
                if "Invalid authentication credentials" in error_message:
                    self.authenticated = False
            self.auth_ready.clear()
            return

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
            self.last_status_message = f"收到 {channel} 資料"

            if channel == "books":
                state.book = data
                summary = summarise_book(data)
                if summary:
                    state.book_history.append(summary)
                    self._analyse_order_book_change(symbol, state, state.last_trade)

            elif channel == "trades":
                state.last_trade = data
                serial = data.get("serial")
                if serial != state.last_processed_trade_serial:
                    state.last_processed_trade_serial = serial
                    state.trades.appendleft(data)
                    state.trade_history.append(
                        {
                            "time": float(data.get("time") or now_taipei().timestamp()),
                            "price": float(data.get("price") or 0),
                            "size": int(data.get("size") or 0),
                            "serial": serial,
                        }
                    )
                    self._update_opening_state(symbol, state, data)
                    self._analyse_order_book_change(symbol, state, data)

    def _safe_subscribe(self, channel: str, symbol: str) -> bool:
        if self.stock is None:
            return False
        try:
            self.stock.subscribe({"channel": channel, "symbol": symbol})
            return True
        except Exception as exc:
            with self.lock:
                self.connected = False
                self.error_message = f"訂閱失敗：{channel} {symbol} - {exc}"
                self.last_status_message = "送出訂閱時發生例外"
            self.connection_ready.clear()
            self.auth_ready.clear()
            return False

    def _flush_pending_subscriptions(self) -> None:
        with self.lock:
            if not self.connected or not self.authenticated:
                return
            pending_items = list(self.pending_subscriptions)

        for channel, symbol in pending_items:
            if self._safe_subscribe(channel, symbol):
                with self.lock:
                    self.pending_subscriptions.discard((channel, symbol))
                    self.subscriptions.add((channel, symbol))
            else:
                break

    def subscribe_symbols(self, symbols: list[str]) -> None:
        if not self.api_key or WebSocketClient is None:
            return

        self.ensure_started()
        for symbol in symbols:
            for channel in ("books", "trades"):
                key = (channel, symbol)
                with self.lock:
                    if key not in self.subscriptions:
                        self.pending_subscriptions.add(key)

        if self.stock is None:
            with self.lock:
                if self.error_message is None:
                    self.error_message = "正在初始化 Fugle SDK，請稍候。"
                    self.last_status_message = "等待 SDK 建立 stock client"
            return

        if not self.connection_ready.wait(timeout=1.0):
            with self.lock:
                if self.error_message is None:
                    self.error_message = "正在建立 WebSocket 連線，請稍候。"
                    self.last_status_message = "等待 WebSocket connect"
            return

        if not self.auth_ready.wait(timeout=2.0):
            with self.lock:
                if self.error_message is None:
                    self.error_message = "WebSocket 已連線，但尚未完成 API 驗證。"
                    self.last_status_message = "等待 authenticated 事件"
            return

        self._flush_pending_subscriptions()

    def snapshot(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        with self.lock:
            result: dict[str, dict[str, Any]] = {}
            for symbol in symbols:
                state = self.states[symbol]
                result[symbol] = {
                    "book": state.book,
                    "last_trade": state.last_trade,
                    "trades": list(state.trades),
                    "signal_events": list(state.signal_events),
                    "book_summary": state.book_history[-1] if state.book_history else None,
                    "open_trade": state.open_trade,
                    "session_high": state.session_high,
                    "session_low": state.session_low,
                    "trade_history": list(state.trade_history),
                }
            return result

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "connected": self.connected,
                "authenticated": self.authenticated,
                "error_message": self.error_message,
                "last_event_at": self.last_event_at,
                "last_status_message": self.last_status_message,
                "subscriptions": len(self.subscriptions),
                "pending_subscriptions": len(self.pending_subscriptions),
            }


@st.cache_resource
def get_store(api_key: str | None) -> FugleRealtimeStore:
    store = FugleRealtimeStore(api_key)
    store.ensure_started()
    return store


def build_demo_signals(symbols: list[str], snapshots: dict[str, dict[str, Any]]) -> dict[str, list[SignalEvent]]:
    result: dict[str, list[SignalEvent]] = {}
    for idx, symbol in enumerate(symbols):
        if symbol not in snapshots:
            result[symbol] = []
            continue
        if idx % 2 == 0:
            result[symbol] = [
                SignalEvent(
                    event_type="bid_stack_up",
                    side="買盤",
                    message=f"{symbol} 買盤近價掛單集中，示範訊號。",
                    score=0.74,
                )
            ]
        else:
            result[symbol] = [
                SignalEvent(
                    event_type="ask_pull",
                    side="賣盤",
                    message=f"{symbol} 賣盤五檔快速減少，示範訊號。",
                    score=0.68,
                )
            ]
    return result


def calc_symbol_signal_score(symbol_data: dict[str, Any], index_events: list[SignalEvent]) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    for event in symbol_data.get("signal_events", [])[:5]:
        if event.side == "買盤":
            score += event.score
            reasons.append(event.message)
        elif event.side == "賣盤":
            score -= event.score
            reasons.append(event.message)
        elif event.side == "開盤":
            reasons.append(event.message)

    open_trade = symbol_data.get("open_trade")
    last_trade = symbol_data.get("last_trade")
    session_high = symbol_data.get("session_high")
    session_low = symbol_data.get("session_low")

    if open_trade and last_trade:
        open_price = float(open_trade.get("price") or 0)
        last_price = float(last_trade.get("price") or 0)
        if open_price > 0 and last_price > 0:
            intraday_move_pct = (last_price - open_price) / open_price * 100
            if intraday_move_pct >= 1.2:
                score += 0.8
                reasons.append(f"現價相對開盤上漲 {intraday_move_pct:.2f}%。")
            elif intraday_move_pct <= -1.2:
                score -= 0.8
                reasons.append(f"現價相對開盤下跌 {abs(intraday_move_pct):.2f}%。")

    if last_trade and session_high and session_low:
        last_price = float(last_trade.get("price") or 0)
        if session_high and last_price >= session_high * 0.997:
            score += 0.35
            reasons.append("價格接近盤中高點。")
        if session_low and last_price <= session_low * 1.003:
            score -= 0.35
            reasons.append("價格接近盤中低點。")

    for event in index_events[:2]:
        change_pct = float(event.extra.get("change_pct", 0.0))
        if change_pct > 0:
            score += 0.4
        elif change_pct < 0:
            score -= 0.4
        reasons.append(event.message)

    return score, reasons[:6]


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
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
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
        for item in list(trades)[:20]
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def render_book_summary(summary: dict[str, Any] | None) -> None:
    st.subheader("五檔結構摘要")
    if not summary:
        st.info("尚未累積足夠五檔結構。")
        return

    cols = st.columns(4)
    cols[0].metric("買盤總量", f"{int(summary['bid_total']):,}")
    cols[1].metric("賣盤總量", f"{int(summary['ask_total']):,}")
    cols[2].metric("買前三檔占比", f"{summary['bid_near3_ratio']:.0%}")
    cols[3].metric("賣前三檔占比", f"{summary['ask_near3_ratio']:.0%}")


def render_signal_panel(symbol: str, signal_events: list[SignalEvent]) -> None:
    st.subheader(f"{symbol} 異常訊號")
    if not signal_events:
        st.info("目前尚未偵測到明顯的五檔或成交異常。")
        return

    rows = []
    for event in signal_events[:8]:
        rows.append(
            {
                "時間": event.created_at.strftime("%H:%M:%S"),
                "方向": event.side,
                "類型": event.event_type,
                "強度": classify_severity(event.score),
                "內容": event.message,
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def render_opening_panel(symbol: str, symbol_data: dict[str, Any]) -> None:
    st.subheader(f"{symbol} 開盤追蹤")
    open_trade = symbol_data.get("open_trade")
    last_trade = symbol_data.get("last_trade")
    session_high = symbol_data.get("session_high")
    session_low = symbol_data.get("session_low")

    if not open_trade:
        st.info("尚未記錄到第一筆開盤成交。")
        return

    open_price = float(open_trade.get("price") or 0)
    last_price = float(last_trade.get("price") or 0) if last_trade else 0
    move_pct = 0.0 if open_price == 0 or last_price == 0 else (last_price - open_price) / open_price * 100

    cols = st.columns(4)
    cols[0].metric("開盤第一筆", f"{open_price:,.2f}")
    cols[1].metric("目前相對開盤", f"{move_pct:+.2f}%")
    cols[2].metric("盤中高點", f"{session_high:,.2f}" if session_high else "-")
    cols[3].metric("盤中低點", f"{session_low:,.2f}" if session_low else "-")


def render_decision_panel(symbol: str, symbol_data: dict[str, Any], index_events: list[SignalEvent]) -> None:
    st.subheader(f"{symbol} 綜合判斷")
    score, reasons = calc_symbol_signal_score(symbol_data, index_events)
    bias = score_to_bias(score)

    cols = st.columns(3)
    cols[0].metric("綜合分數", f"{score:+.2f}")
    cols[1].metric("判斷", bias)
    cols[2].metric("依據數", len(reasons))

    if not reasons:
        st.info("目前資料不足，尚未形成明確的多空觀察結論。")
        return

    reason_rows = [{"說明": reason} for reason in reasons]
    st.dataframe(pd.DataFrame(reason_rows), width="stretch", hide_index=True)


def get_raw_api_key() -> tuple[str | None, str]:
    if "FUGLE_API_KEY" in st.secrets:
        return st.secrets["FUGLE_API_KEY"], "Streamlit secrets"
    env_value = os.getenv("FUGLE_API_KEY")
    if env_value:
        return env_value, "環境變數"
    return None, "未載入"


def render_sidebar_benchmark_section(benchmark_result: dict[str, Any]) -> None:
    st.markdown("---")
    st.subheader("全球指數參考")
    st.caption("此區為參考數據，可能為延遲報價，非交易所即時成交。")

    for item in benchmark_result.get("items", []):
        label = item.get("label", "-")
        price = item.get("price")
        change = item.get("change")
        change_pct = item.get("change_pct")
        symbol = item.get("symbol", "-")
        note = item.get("note", "參考")
        timestamp = item.get("time", "-")

        if price is None:
            price_text = "-"
            delta = "資料暫缺"
        else:
            sign = "+" if change is not None and change > 0 else ""
            delta = f"{sign}{change:,.2f} ({sign}{change_pct:.2f}%)" if change is not None and change_pct is not None else "-"
            price_text = f"{price:,.2f}"

        st.metric(label, price_text, delta=delta)
        st.caption(f"{timestamp} | {symbol}")
        st.caption(note)

    if benchmark_result.get("message"):
        st.caption(benchmark_result["message"])


def update_index_shock_signals(benchmark_result: dict[str, Any]) -> list[SignalEvent]:
    if "index_signal_history" not in st.session_state:
        st.session_state.index_signal_history = deque(maxlen=120)
    if "index_signal_events" not in st.session_state:
        st.session_state.index_signal_events = deque(maxlen=20)
    if "index_signal_cooldowns" not in st.session_state:
        st.session_state.index_signal_cooldowns = {}

    twii_item = next((item for item in benchmark_result.get("items", []) if item.get("symbol") == "^TWII"), None)
    if not twii_item or twii_item.get("price") is None:
        return list(st.session_state.index_signal_events)

    now_ts = now_taipei().timestamp()
    st.session_state.index_signal_history.append({"time": now_ts, "price": float(twii_item["price"])})
    history = list(st.session_state.index_signal_history)
    if len(history) < 2:
        return list(st.session_state.index_signal_events)

    recent_15s = [item for item in history if now_ts - item["time"] <= 15]
    if len(recent_15s) >= 2:
        base_price = recent_15s[0]["price"]
        latest_price = recent_15s[-1]["price"]
        change_pct = 0.0 if base_price == 0 else (latest_price - base_price) / base_price * 100
        cooldown_key = "twii_shock"
        last_emitted = st.session_state.index_signal_cooldowns.get(cooldown_key, 0.0)

        if abs(change_pct) >= 0.35 and now_ts - last_emitted >= 20:
            direction = "偏多" if change_pct > 0 else "偏空"
            message = f"台灣加權指數 15 秒變動 {change_pct:+.2f}%，大盤出現明顯 {direction} 異動。"
            score = min(0.95, 0.6 + abs(change_pct))
            st.session_state.index_signal_events.appendleft(
                SignalEvent(
                    event_type="twii_shock",
                    side="大盤",
                    message=message,
                    score=score,
                    extra={"change_pct": change_pct},
                )
            )
            st.session_state.index_signal_cooldowns[cooldown_key] = now_ts

    return list(st.session_state.index_signal_events)


def render_index_signal_panel(index_events: list[SignalEvent]) -> None:
    st.subheader("大盤異動提示")
    if not index_events:
        st.info("目前尚未偵測到台灣加權指數的明顯急變。")
        return

    rows = [
        {
            "時間": event.created_at.strftime("%H:%M:%S"),
            "強度": classify_severity(event.score),
            "內容": event.message,
        }
        for event in index_events[:5]
    ]
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


st.set_page_config(page_title="台股即時監控台", page_icon=":bar_chart:", layout="wide")

st.title("台股即時監控台")
st.caption("使用 Streamlit 製作的台股五檔委買委賣、即時成交與異常訊號監控頁面。")

with st.sidebar:
    st.header("監控設定")
    symbols_raw = st.text_input("股票代碼", value=", ".join(DEFAULT_SYMBOLS), help="請用逗號分隔，例如：2330, 2317")
    symbols = normalize_symbols(symbols_raw) or DEFAULT_SYMBOLS
    refresh_seconds = st.slider("刷新秒數", min_value=1, max_value=10, value=1)
    st.caption("Fugle 免費方案有訂閱數限制，每個股票代碼會同時使用 books 與 trades 兩個頻道。")

raw_api_key, api_key_source = get_raw_api_key()
api_key, api_key_note = normalize_fugle_api_key(raw_api_key)
using_mock = not api_key or WebSocketClient is None
benchmark_result = fetch_benchmark_data()
index_signal_events = update_index_shock_signals(benchmark_result)

with st.sidebar:
    render_sidebar_benchmark_section(benchmark_result)

if using_mock:
    st.warning("目前為示範模式。請在 Streamlit secrets 設定 FUGLE_API_KEY 後切換為即時行情。")
    snapshots = build_mock_snapshot(symbols)
    demo_signals = build_demo_signals(symbols, snapshots)
    status = {
        "connected": False,
        "authenticated": False,
        "error_message": None if WebSocketClient is not None else "尚未安裝 fugle-marketdata 套件。",
        "last_event_at": now_taipei(),
        "last_status_message": "示範模式",
        "subscriptions": 0,
        "pending_subscriptions": 0,
    }
    rest_result = {"ok": False, "message": "示範模式下不執行 REST 測試。", "data": None}
else:
    store = get_store(api_key)
    store.subscribe_symbols(symbols)
    snapshots = store.snapshot(symbols)
    demo_signals = {}
    status = store.status()
    rest_result = test_rest_quote(api_key, symbols[0])

status_cols = st.columns(6)
status_cols[0].metric("模式", "即時" if not using_mock else "示範")
status_cols[1].metric("連線", "已連線" if status.get("connected") else "未連線")
status_cols[2].metric("驗證", "成功" if status.get("authenticated") else "未完成")
status_cols[3].metric("已訂閱", status.get("subscriptions", 0))
status_cols[4].metric("待訂閱", status.get("pending_subscriptions", 0))
status_cols[5].metric("最後事件", status["last_event_at"].strftime("%H:%M:%S") if status.get("last_event_at") else "-")

if status.get("error_message"):
    st.error(status["error_message"])

render_index_signal_panel(index_signal_events)

with st.expander("連線診斷"):
    st.write(f"API key 來源：{api_key_source}")
    st.write(f"API key 狀態：{mask_secret(raw_api_key)}")
    st.write(f"API key 處理：{api_key_note}")
    st.write(f"目前模式：{'即時' if not using_mock else '示範'}")
    st.write(f"連線狀態：{'已連線' if status.get('connected') else '未連線'}")
    st.write(f"驗證狀態：{'成功' if status.get('authenticated') else '未完成'}")
    st.write(f"狀態訊息：{status.get('last_status_message') or '-'}")
    st.write(f"錯誤訊息：{status.get('error_message') or '-'}")

with st.expander("REST 測試"):
    st.write(f"測試標的：{symbols[0] if symbols else DEFAULT_SYMBOLS[0]}")
    st.write(f"測試結果：{'成功' if rest_result.get('ok') else '失敗'}")
    st.write(f"訊息：{rest_result.get('message')}")
    if rest_result.get("ok") and rest_result.get("data"):
        st.json(rest_result["data"])

tabs = st.tabs(symbols)
for tab, symbol in zip(tabs, symbols):
    with tab:
        if not using_mock:
            current_snapshots = store.snapshot([symbol])
            symbol_data = current_snapshots.get(symbol, {})
            signal_events = symbol_data.get("signal_events", [])
        else:
            symbol_data = snapshots.get(symbol, {})
            signal_events = demo_signals.get(symbol, [])

        summary = symbol_data.get("book_summary")

        top_left, top_right = st.columns([1, 1])
        with top_left:
            render_order_book(symbol, symbol_data.get("book"))
        with top_right:
            render_trade_summary(symbol, symbol_data.get("last_trade"))

        render_trade_tape(symbol_data.get("trades", []))

        mid_left, mid_right = st.columns([1.3, 1])
        with mid_left:
            render_signal_panel(symbol, signal_events)
        with mid_right:
            render_book_summary(summary)

        bottom_left, bottom_right = st.columns([1, 1])
        with bottom_left:
            render_opening_panel(symbol, symbol_data)
        with bottom_right:
            render_decision_panel(symbol, symbol_data, index_signal_events)

if refresh_seconds > 0:
    time.sleep(refresh_seconds)
    st.rerun()

with st.expander("部署說明"):
    st.markdown(
        """
        - 本系統使用官方 `fugle-marketdata` Python SDK 串接台股即時行情。
        - 原始碼可放在 GitHub，並由 Streamlit Community Cloud 直接部署。
        - 全球指數區為參考用途，可能為延遲報價，不建議直接作為交易依據。
        - 異常訊號屬規則式監控，適合盤中輔助判讀，不代表保證性的買賣建議。
        """
    )
