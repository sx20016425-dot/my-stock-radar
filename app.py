from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from typing import Literal

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None


FeatureName = Literal["RSI", "WT", "CCI", "ADX"]


@dataclass
class FeatureConfig:
    name: FeatureName
    param_a: int
    param_b: int


@dataclass
class LorentzianConfig:
    source: str = "close"
    neighbors_count: int = 10
    max_bars_back: int = 5000
    feature_count: int = 5
    color_compression: int = 1
    use_dynamic_exits: bool = False
    use_volatility_filter: bool = True
    use_regime_filter: bool = True
    use_adx_filter: bool = False
    regime_threshold: float = -0.1
    adx_threshold: int = 20
    use_ema_filter: bool = False
    ema_period: int = 200
    use_sma_filter: bool = False
    sma_period: int = 200
    use_kernel_filter: bool = True
    use_kernel_smoothing: bool = False
    h: int = 8
    r: float = 8.0
    x: int = 25
    lag: int = 2
    hold_bars: int = 4
    initial_capital: float = 1_000_000.0
    fee_bps: float = 1.425
    tax_bps_sell: float = 3.0
    features: tuple[FeatureConfig, ...] = (
        FeatureConfig("RSI", 14, 1),
        FeatureConfig("WT", 10, 11),
        FeatureConfig("CCI", 20, 1),
        FeatureConfig("ADX", 20, 2),
        FeatureConfig("RSI", 9, 1),
    )


def load_ohlcv(csv_path: str | None, ticker: str | None, period: str, interval: str) -> pd.DataFrame:
    if csv_path:
        df = pd.read_csv(csv_path)
    elif ticker:
        if yf is None:
            raise RuntimeError("yfinance 未安裝，無法直接下載資料。請改用 --csv。")
        df = yf.download(ticker, period=period, interval=interval, auto_adjust=False, progress=False)
        df = df.reset_index()
    else:
        raise ValueError("請提供 --csv 或 --ticker 其中一種資料來源。")

    rename_map = {col: col.lower() for col in df.columns}
    df = df.rename(columns=rename_map)

    if "datetime" in df.columns:
        dt_col = "datetime"
    elif "date" in df.columns:
        dt_col = "date"
    else:
        dt_col = None

    required = {"open", "high", "low", "close"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"資料缺少必要欄位：{', '.join(missing)}")

    if dt_col:
        df[dt_col] = pd.to_datetime(df[dt_col], errors="coerce")
        df = df.sort_values(dt_col).reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)

    if "volume" not in df.columns:
        df["volume"] = 0

    df["hlc3"] = (df["high"] + df["low"] + df["close"]) / 3.0
    df["ohlc4"] = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0
    return df


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=max(length, 1), adjust=False).mean()


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(max(length, 1), min_periods=max(length, 1)).mean()


def rsi(series: pd.Series, length: int) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    avg_up = up.ewm(alpha=1 / max(length, 1), adjust=False).mean()
    avg_down = down.ewm(alpha=1 / max(length, 1), adjust=False).mean()
    rs = avg_up / avg_down.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def cci(series: pd.Series, length: int) -> pd.Series:
    mean = series.rolling(length, min_periods=length).mean()
    mad = series.rolling(length, min_periods=length).apply(
        lambda x: float((pd.Series(x) - pd.Series(x).mean()).abs().mean()) if len(x) else math.nan,
        raw=False,
    )
    return (series - mean) / (0.015 * mad.replace(0, pd.NA))


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    ranges = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def adx(df: pd.DataFrame, length: int) -> pd.Series:
    up_move = df["high"].diff()
    down_move = -df["low"].diff()
    plus_dm = pd.Series(0.0, index=df.index)
    minus_dm = pd.Series(0.0, index=df.index)
    plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
    minus_dm[(down_move > up_move) & (down_move > 0)] = down_move
    atr = true_range(df).ewm(alpha=1 / max(length, 1), adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / max(length, 1), adjust=False).mean() / atr.replace(0, pd.NA)
    minus_di = 100 * minus_dm.ewm(alpha=1 / max(length, 1), adjust=False).mean() / atr.replace(0, pd.NA)
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)).fillna(0)
    return dx.ewm(alpha=1 / max(length, 1), adjust=False).mean()


def wave_trend(hlc3: pd.Series, channel_length: int, average_length: int) -> pd.Series:
    esa = ema(hlc3, channel_length)
    d = ema((hlc3 - esa).abs(), channel_length)
    ci = (hlc3 - esa) / (0.015 * d.replace(0, pd.NA))
    return ema(ci, average_length)


def feature_series(df: pd.DataFrame, feature: FeatureConfig) -> pd.Series:
    if feature.name == "RSI":
        raw = rsi(df["close"], feature.param_a)
        return ema(raw, feature.param_b) if feature.param_b > 1 else raw
    if feature.name == "WT":
        return wave_trend(df["hlc3"], feature.param_a, feature.param_b)
    if feature.name == "CCI":
        raw = cci(df["close"], feature.param_a)
        return ema(raw, feature.param_b) if feature.param_b > 1 else raw
    if feature.name == "ADX":
        raw = adx(df, feature.param_a)
        return ema(raw, feature.param_b) if feature.param_b > 1 else raw
    raise ValueError(f"不支援的特徵：{feature.name}")


def volatility_filter(df: pd.DataFrame) -> pd.Series:
    short_vol = df["close"].pct_change().rolling(10, min_periods=10).std()
    long_vol = df["close"].pct_change().rolling(40, min_periods=40).std()
    return (short_vol > long_vol * 0.5).fillna(False)


def regime_filter(df: pd.DataFrame, threshold: float) -> pd.Series:
    baseline = ema(df["close"], 20)
    atr = true_range(df).rolling(20, min_periods=20).mean()
    regime = ((baseline - baseline.shift(5)) / atr.replace(0, pd.NA)).fillna(0)
    return regime > threshold


def rational_quadratic_kernel(series: pd.Series, lookback: int, relative_weight: float, start_at_bar: int) -> pd.Series:
    values: list[float] = []
    idx = series.index
    lb = max(lookback, 2)
    rw = max(relative_weight, 0.1)
    start = max(start_at_bar, 1)
    for i in range(len(series)):
        if i < start:
            values.append(math.nan)
            continue
        begin = max(0, i - lb + 1)
        window = series.iloc[begin : i + 1]
        distances = list(range(len(window)))[::-1]
        weights = [(1 + ((d * d) / (2 * rw * lb * lb))) ** (-rw) for d in distances]
        weight_sum = sum(weights)
        values.append(float((window * weights).sum() / weight_sum) if weight_sum else math.nan)
    return pd.Series(values, index=idx)


def gaussian_kernel(series: pd.Series, lookback: int, start_at_bar: int) -> pd.Series:
    values: list[float] = []
    idx = series.index
    lb = max(lookback, 2)
    sigma = max(lb / 2, 1)
    start = max(start_at_bar, 1)
    for i in range(len(series)):
        if i < start:
            values.append(math.nan)
            continue
        begin = max(0, i - lb + 1)
        window = series.iloc[begin : i + 1]
        distances = list(range(len(window)))[::-1]
        weights = [math.exp(-((d * d) / (2 * sigma * sigma))) for d in distances]
        weight_sum = sum(weights)
        values.append(float((window * weights).sum() / weight_sum) if weight_sum else math.nan)
    return pd.Series(values, index=idx)


def lorentzian_distance(current: list[float], candidate: list[float]) -> float:
    total = 0.0
    for a, b in zip(current, candidate):
        total += math.log(1 + abs(a - b))
    return total


def prepare_dataframe(df: pd.DataFrame, config: LorentzianConfig) -> pd.DataFrame:
    work = df.copy()

    for idx, feature in enumerate(config.features[: config.feature_count], start=1):
        work[f"f{idx}"] = feature_series(work, feature)

    work["ema_filter"] = True if not config.use_ema_filter else (work["close"] > ema(work["close"], config.ema_period))
    work["ema_down_filter"] = True if not config.use_ema_filter else (work["close"] < ema(work["close"], config.ema_period))
    work["sma_filter"] = True if not config.use_sma_filter else (work["close"] > sma(work["close"], config.sma_period))
    work["sma_down_filter"] = True if not config.use_sma_filter else (work["close"] < sma(work["close"], config.sma_period))

    work["filter_volatility"] = True if not config.use_volatility_filter else volatility_filter(work)
    work["filter_regime"] = True if not config.use_regime_filter else regime_filter(work, config.regime_threshold)
    work["filter_adx"] = True if not config.use_adx_filter else (adx(work, 14) > config.adx_threshold)
    work["filter_all"] = work["filter_volatility"] & work["filter_regime"] & work["filter_adx"]

    yhat1 = rational_quadratic_kernel(work[config.source], config.h, config.r, config.x)
    yhat2 = gaussian_kernel(work[config.source], max(config.h - config.lag, 2), config.x)
    work["kernel_estimate"] = yhat1
    work["is_bullish_rate"] = yhat1.diff() > 0
    work["is_bearish_rate"] = yhat1.diff() < 0
    work["is_bullish_smooth"] = yhat2 >= yhat1
    work["is_bearish_smooth"] = yhat2 <= yhat1
    work["is_bullish"] = True
    work["is_bearish"] = True
    if config.use_kernel_filter:
        if config.use_kernel_smoothing:
            work["is_bullish"] = work["is_bullish_smooth"].fillna(False)
            work["is_bearish"] = work["is_bearish_smooth"].fillna(False)
        else:
            work["is_bullish"] = work["is_bullish_rate"].fillna(False)
            work["is_bearish"] = work["is_bearish_rate"].fillna(False)

    work["label"] = 0
    future_close = work[config.source].shift(-config.hold_bars)
    work.loc[future_close > work[config.source], "label"] = 1
    work.loc[future_close < work[config.source], "label"] = -1
    return work


def run_lorentzian_model(df: pd.DataFrame, config: LorentzianConfig) -> pd.DataFrame:
    work = prepare_dataframe(df, config)
    feature_cols = [f"f{i}" for i in range(1, config.feature_count + 1)]

    predictions: list[float] = [math.nan] * len(work)
    signals: list[int] = [0] * len(work)

    start_index = max(config.max_bars_back, 100)
    for i in range(len(work)):
        row = work.iloc[i]
        if i < start_index or row[feature_cols].isna().any():
            continue

        train_start = max(0, i - config.max_bars_back)
        train_end = max(train_start, i - config.hold_bars)
        candidate_idx = list(range(train_start, train_end, config.hold_bars))
        current_features = [float(row[col]) for col in feature_cols]
        scored: list[tuple[float, int]] = []

        for j in candidate_idx:
            candidate = work.iloc[j]
            if candidate[feature_cols].isna().any():
                continue
            label = int(candidate["label"])
            if label == 0:
                continue
            distance = lorentzian_distance(current_features, [float(candidate[col]) for col in feature_cols])
            scored.append((distance, label))

        if not scored:
            continue

        scored.sort(key=lambda item: item[0])
        nearest = scored[: config.neighbors_count]
        prediction = float(sum(label for _, label in nearest))
        predictions[i] = prediction

        prev_signal = signals[i - 1] if i > 0 else 0
        if prediction > 0 and bool(row["filter_all"]):
            signals[i] = 1
        elif prediction < 0 and bool(row["filter_all"]):
            signals[i] = -1
        else:
            signals[i] = prev_signal

    work["prediction"] = predictions
    work["signal"] = signals
    work["signal_change"] = work["signal"].diff().fillna(0)
    work["bars_held"] = 0

    bars_held = 0
    for i in range(len(work)):
        if i == 0 or work.iloc[i]["signal"] != work.iloc[i - 1]["signal"]:
            bars_held = 0
        else:
            bars_held += 1
        work.iat[i, work.columns.get_loc("bars_held")] = bars_held

    work["is_new_buy_signal"] = (work["signal"] == 1) & (work["signal_change"] != 0)
    work["is_new_sell_signal"] = (work["signal"] == -1) & (work["signal_change"] != 0)
    work["start_long_trade"] = work["is_new_buy_signal"] & work["is_bullish"] & work["ema_filter"] & work["sma_filter"]
    work["start_short_trade"] = work["is_new_sell_signal"] & work["is_bearish"] & work["ema_down_filter"] & work["sma_down_filter"]
    return work


def backtest(df: pd.DataFrame, config: LorentzianConfig) -> tuple[pd.DataFrame, dict[str, float]]:
    work = run_lorentzian_model(df, config)
    trades: list[dict[str, float | str | int]] = []
    position = 0
    entry_price = 0.0
    entry_index = -1

    fee_rate = config.fee_bps / 10000
    tax_sell_rate = config.tax_bps_sell / 10000

    for i in range(len(work)):
        row = work.iloc[i]
        close_price = float(row["close"])

        if position == 0:
            if bool(row["start_long_trade"]):
                position = 1
                entry_price = close_price
                entry_index = i
            elif bool(row["start_short_trade"]):
                position = -1
                entry_price = close_price
                entry_index = i
            continue

        bars_in_trade = i - entry_index
        exit_now = bars_in_trade >= config.hold_bars

        if position == 1 and bool(row["start_short_trade"]):
            exit_now = True
        if position == -1 and bool(row["start_long_trade"]):
            exit_now = True

        if not exit_now:
            continue

        gross_return = ((close_price - entry_price) / entry_price) if position == 1 else ((entry_price - close_price) / entry_price)
        cost = (fee_rate * 2) + (tax_sell_rate if position == 1 else 0)
        net_return = gross_return - cost
        trades.append(
            {
                "entry_index": entry_index,
                "exit_index": i,
                "side": "LONG" if position == 1 else "SHORT",
                "entry_price": entry_price,
                "exit_price": close_price,
                "bars": bars_in_trade,
                "gross_return_pct": gross_return * 100,
                "net_return_pct": net_return * 100,
            }
        )
        position = 0
        entry_price = 0.0
        entry_index = -1

    trades_df = pd.DataFrame(trades)
    if trades_df.empty:
        return trades_df, {
            "total_trades": 0,
            "win_rate_pct": 0.0,
            "avg_return_pct": 0.0,
            "total_return_pct": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
        }

    equity_curve = (1 + trades_df["net_return_pct"] / 100).cumprod()
    rolling_peak = equity_curve.cummax()
    drawdown = (equity_curve / rolling_peak - 1) * 100

    wins = trades_df[trades_df["net_return_pct"] > 0]
    losses = trades_df[trades_df["net_return_pct"] <= 0]
    gross_profit = wins["net_return_pct"].sum()
    gross_loss = abs(losses["net_return_pct"].sum())

    stats = {
        "total_trades": float(len(trades_df)),
        "win_rate_pct": float((len(wins) / len(trades_df)) * 100),
        "avg_return_pct": float(trades_df["net_return_pct"].mean()),
        "total_return_pct": float((equity_curve.iloc[-1] - 1) * 100),
        "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
        "max_drawdown_pct": float(drawdown.min()),
    }
    return trades_df, stats


def print_report(trades_df: pd.DataFrame, stats: dict[str, float]) -> None:
    print("=== Lorentzian Classification 簡化版回測 ===")
    print(f"總交易次數: {int(stats['total_trades'])}")
    print(f"勝率: {stats['win_rate_pct']:.2f}%")
    print(f"平均單筆報酬: {stats['avg_return_pct']:.3f}%")
    print(f"總報酬: {stats['total_return_pct']:.2f}%")
    print(f"Profit Factor: {stats['profit_factor']:.3f}")
    print(f"最大回撤: {stats['max_drawdown_pct']:.2f}%")
    if not trades_df.empty:
        print("\n最近 10 筆交易:")
        print(trades_df.tail(10).to_string(index=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lorentzian Classification 簡化版 Python 回測")
    parser.add_argument("--csv", help="OHLCV CSV 檔案路徑")
    parser.add_argument("--ticker", help="使用 yfinance 下載資料，例如 AAPL 或 2330.TW")
    parser.add_argument("--period", default="2y", help="yfinance period，預設 2y")
    parser.add_argument("--interval", default="1d", help="yfinance interval，預設 1d")
    parser.add_argument("--max-bars-back", type=int, default=5000, help="Max Bars Back，預設 5000")
    parser.add_argument("--neighbors-count", type=int, default=10, help="Neighbors Count，預設 10")
    parser.add_argument("--feature-count", type=int, default=5, choices=[2, 3, 4, 5], help="Feature Count")
    parser.add_argument("--export-trades", help="輸出交易明細 CSV 路徑")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = LorentzianConfig(
        max_bars_back=args.max_bars_back,
        neighbors_count=args.neighbors_count,
        feature_count=args.feature_count,
    )
    df = load_ohlcv(args.csv, args.ticker, args.period, args.interval)
    trades_df, stats = backtest(df, config)
    print_report(trades_df, stats)
    if args.export_trades:
        trades_df.to_csv(args.export_trades, index=False, encoding="utf-8-sig")
        print(f"\n交易明細已輸出至: {args.export_trades}")


if __name__ == "__main__":
    main()
