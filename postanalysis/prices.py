"""Daily price history from Yahoo Finance, cached as one CSV per ticker.

A cached CSV (columns: Date, Close, High, Stock Splits) can also be dropped into the
cache folder by hand for anything Yahoo does not cover; it is used as-is when it spans
the requested dates.
"""

from pathlib import Path

import pandas as pd

PRICE_COLUMNS = ["Close", "High", "Stock Splits"]


def ticker_for(symbol: str, exchanges: set[str]) -> str:
    return f"{symbol}.NS" if "NSE" in exchanges or not exchanges else f"{symbol}.BO"


def _cache_covers(cached: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> bool:
    if cached.empty:
        return False
    # Allow for weekends/holidays at either edge.
    return cached.index.min() <= start + pd.Timedelta(days=5) and cached.index.max() >= end - pd.Timedelta(days=4)


def _download(ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    import yfinance as yf

    # auto_adjust=False: Close is split-adjusted but not dividend-adjusted, which is what
    # we want for comparing against traded prices after scaling them by splits.
    df = yf.Ticker(ticker).history(start=start, end=end + pd.Timedelta(days=1), auto_adjust=False, actions=True)
    if df.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.index.name = "Date"
    for col in PRICE_COLUMNS:
        if col not in df.columns:
            df[col] = 0.0
    return df[PRICE_COLUMNS]


def get_history(ticker: str, start, end, cache_dir) -> pd.DataFrame:
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    cache = Path(cache_dir) / f"{ticker}.csv"
    if cache.exists():
        cached = pd.read_csv(cache, index_col="Date", parse_dates=["Date"])
        for col in PRICE_COLUMNS:
            if col not in cached.columns:
                cached[col] = 0.0
        if _cache_covers(cached, start, end):
            return cached.loc[start:end, PRICE_COLUMNS]
    fresh = _download(ticker, start, end)
    if not fresh.empty:
        cache.parent.mkdir(parents=True, exist_ok=True)
        fresh.to_csv(cache)
    return fresh


def split_factor_after(history: pd.DataFrame, date) -> float:
    """Product of split/bonus ratios strictly after `date` (1.0 if none)."""
    splits = history.loc[history.index > pd.Timestamp(date), "Stock Splits"]
    splits = splits[splits > 0]
    return float(splits.prod()) if not splits.empty else 1.0
