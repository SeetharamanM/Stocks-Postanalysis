"""Valuation and risk parameters at a point in time: PE, PEG, beta and alpha.

EPS comes from Yahoo Finance's reported income statements (about 4 annual and 5-6 quarterly
periods), cached as one JSON file per ticker. PE on a date uses the EPS of periods that had
ended by then, with the share price as it actually traded on that day (not split-adjusted),
so both are in the same share count.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .prices import split_factor_after

EPS_ROWS = ["Diluted EPS", "Basic EPS"]
INFO_FIELDS = ["shortName", "sector", "industry", "marketCap", "trailingPE", "forwardPE", "pegRatio",
               "trailingPegRatio", "priceToBook", "trailingEps", "beta", "dividendYield"]
MAX_AGE_DAYS = 7
INDEX_TICKER = "^NSEI"  # NIFTY 50


def _eps_series(statement: pd.DataFrame) -> dict[str, float]:
    if statement is None or statement.empty:
        return {}
    for row in EPS_ROWS:
        if row in statement.index:
            series = pd.to_numeric(statement.loc[row], errors="coerce").dropna()
            return {pd.Timestamp(d).strftime("%Y-%m-%d"): float(v) for d, v in series.items() if pd.notna(d)}
    return {}


def _download(ticker: str) -> dict:
    import yfinance as yf

    t = yf.Ticker(ticker)
    try:
        info = t.info or {}
    except Exception:
        info = {}
    return {
        "fetched": pd.Timestamp.today().strftime("%Y-%m-%d"),
        "annual_eps": _eps_series(t.income_stmt),
        "quarterly_eps": _eps_series(t.quarterly_income_stmt),
        "info": {k: info.get(k) for k in INFO_FIELDS},
    }


def get_fundamentals(ticker: str, cache_dir, refresh: bool = False) -> dict:
    """Reported EPS history and current ratios for `ticker`, cached for a week."""
    cache = Path(cache_dir) / f"{ticker}.json"
    if cache.exists() and not refresh:
        data = json.loads(cache.read_text())
        if (pd.Timestamp.today() - pd.Timestamp(data.get("fetched", "1970-01-01"))).days <= MAX_AGE_DAYS:
            return data
    data = _download(ticker)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, indent=1))
    return data


def _periods(eps: dict[str, float] | None) -> pd.Series:
    """EPS by period end, always date-indexed (an empty dict would otherwise get a number index)."""
    eps = eps or {}
    index = pd.DatetimeIndex([pd.Timestamp(k) for k in eps], name="Period")
    return pd.Series(list(eps.values()), index=index, dtype=float).dropna().sort_index()


def eps_ttm_at(fund: dict, date) -> tuple[float, str]:
    """Trailing-twelve-month EPS known at `date` and how it was derived."""
    date = pd.Timestamp(date)
    quarters = _periods(fund.get("quarterly_eps", {}))
    quarters = quarters[quarters.index <= date]
    if len(quarters) >= 4:
        last4 = quarters.iloc[-4:]
        # Four consecutive quarters span ~9 months between the first and last period end.
        if (last4.index[-1] - last4.index[0]).days <= 300:
            return float(last4.sum()), f"TTM to {last4.index[-1]:%b %Y}"
    annual = _periods(fund.get("annual_eps", {}))
    annual = annual[annual.index <= date]
    if not annual.empty:
        return float(annual.iloc[-1]), f"FY to {annual.index[-1]:%b %Y}"
    return float("nan"), "no EPS before this date"


def eps_growth_at(fund: dict, date) -> float:
    """Year-on-year EPS growth (%) of the last full year reported before `date`."""
    date = pd.Timestamp(date)
    quarters = _periods(fund.get("quarterly_eps", {}))
    quarters = quarters[quarters.index <= date]
    if len(quarters) >= 8 and (quarters.index[-1] - quarters.index[-8]).days <= 700:
        now, before = quarters.iloc[-4:].sum(), quarters.iloc[-8:-4].sum()
    else:
        annual = _periods(fund.get("annual_eps", {}))
        annual = annual[annual.index <= date]
        if len(annual) < 2:
            return float("nan")
        now, before = annual.iloc[-1], annual.iloc[-2]
    if before <= 0:
        return float("nan")  # growth from a loss is not meaningful
    return float((now / before - 1) * 100)


def alpha_beta(stock: pd.Series, index: pd.Series, end, lookback_days: int = 365,
               risk_free: float = 0.065) -> dict:
    """Beta and Jensen's alpha (annualised %) of daily returns over the window ending at `end`."""
    end = pd.Timestamp(end)
    start = end - pd.Timedelta(days=lookback_days)
    prices = pd.concat([stock, index], axis=1, keys=["s", "m"]).loc[start:end].dropna()
    empty = {"Beta": np.nan, "Alpha %": np.nan, "Stock Return %": np.nan, "Index Return %": np.nan}
    if len(prices) < 40:  # need a couple of months of overlapping trading days
        return empty
    rets = prices.pct_change().dropna()
    var = rets["m"].var()
    if not var:
        return empty
    beta = rets["s"].cov(rets["m"]) / var
    rf_daily = (1 + risk_free) ** (1 / 252) - 1
    alpha_daily = (rets["s"].mean() - rf_daily) - beta * (rets["m"].mean() - rf_daily)
    return {
        "Beta": float(beta),
        "Alpha %": float(alpha_daily * 252 * 100),
        "Stock Return %": float((prices["s"].iloc[-1] / prices["s"].iloc[0] - 1) * 100),
        "Index Return %": float((prices["m"].iloc[-1] / prices["m"].iloc[0] - 1) * 100),
    }


def parameters_at(fund: dict, hist: pd.DataFrame, index_close: pd.Series, date, adjusted_price: float,
                  lookback_days: int = 365, risk_free: float = 0.065) -> dict:
    """PE, PEG, beta and alpha on `date`, for a split-adjusted `adjusted_price` from `hist`."""
    traded_price = adjusted_price * split_factor_after(hist, date)
    eps, eps_basis = eps_ttm_at(fund, date)
    pe = traded_price / eps if eps and eps > 0 else np.nan
    growth = eps_growth_at(fund, date)
    peg = pe / growth if growth and growth > 0 and not np.isnan(pe) else np.nan
    out = {"Traded Price": traded_price, "EPS (TTM)": eps, "EPS Basis": eps_basis,
           "PE": pe, "EPS Growth %": growth, "PEG": peg}
    out.update(alpha_beta(hist["Close"], index_close, date, lookback_days, risk_free))
    if eps is not None and not np.isnan(eps) and eps <= 0:
        out["EPS Basis"] += " (loss-making: no PE)"
    return out
