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
                state.last_trade =
