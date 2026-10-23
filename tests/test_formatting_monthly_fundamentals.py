import numpy as np
import pandas as pd

from postanalysis.analysis import financial_year, monthly_realised, yearly_realised
from postanalysis.formatting import group_indian, inr, inr_short
from postanalysis.fundamentals import alpha_beta, eps_growth_at, eps_ttm_at, parameters_at


def test_indian_grouping():
    assert group_indian(999) == "999"
    assert group_indian(151792) == "1,51,792"
    assert group_indian(11786254) == "1,17,86,254"
    assert inr(-459086) == "-₹4,59,086"
    assert inr(2948.5, 2, symbol=False) == "2,948.50"
    assert inr(float("nan")) == ""
    assert inr_short(151792) == "₹1.52 L" and inr_short(-11786254) == "-₹1.18 Cr"


def test_monthly_and_financial_year_pnl():
    sold = pd.DataFrame({
        "ISIN": ["A", "B", "A"],
        "Quantity": [1, 1, 2],
        "Sell Date": pd.to_datetime(["2025-03-10", "2025-03-20", "2025-04-02"]),
        "Sell Price": [110.0, 90.0, 130.0],
        "Invested": [100.0, 100.0, 200.0],
        "Actual P&L": [10.0, -10.0, 60.0],
        "Term": ["STCG", "LTCG", "STCG"],
    })
    assert financial_year(sold["Sell Date"]).tolist() == ["FY2024-25", "FY2024-25", "FY2025-26"]
    m = monthly_realised(sold)
    march = m.iloc[0]
    assert (march["Profit"], march["Loss"], march["Net P&L"]) == (10, -10, 0)
    assert (march["STCG P&L"], march["LTCG P&L"]) == (10, -10)
    y = yearly_realised(m).set_index("FY")
    assert y.loc["FY2025-26", "Net P&L"] == 60 and y.loc["FY2025-26", "Return %"] == 30


FUND = {
    "annual_eps": {"2024-03-31": 8.0, "2025-03-31": 10.0},
    "quarterly_eps": {"2025-03-31": 2.5, "2025-06-30": 3.0, "2025-09-30": 3.0, "2025-12-31": 3.5},
}


def test_eps_ttm_and_growth_use_only_periods_before_the_date():
    assert eps_ttm_at(FUND, "2026-01-15") == (12.0, "TTM to Dec 2025")
    assert eps_ttm_at(FUND, "2025-11-01")[0] == 10.0  # only 3 quarters known -> annual EPS
    assert np.isnan(eps_ttm_at(FUND, "2024-01-01")[0])  # nothing reported yet
    assert eps_growth_at(FUND, "2025-11-01") == 25.0


def test_alpha_beta_on_a_stock_that_doubles_the_index():
    idx = pd.bdate_range("2025-01-01", periods=260)
    rng = np.random.default_rng(1)
    m = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, len(idx)))), idx)
    s = pd.Series(100 * np.exp(np.cumsum(2 * np.log(m).diff().fillna(0))), idx)
    out = alpha_beta(s, m, idx[-1], 365, risk_free=0.0)
    assert abs(out["Beta"] - 2) < 0.05
    assert abs(out["Alpha %"]) < 5


def test_pe_and_peg_at_peak():
    idx = pd.bdate_range("2025-06-01", "2026-02-27")
    hist = pd.DataFrame({"Close": np.linspace(100, 240, len(idx)), "Stock Splits": 0.0}, index=idx)
    p = parameters_at(FUND, hist, hist["Close"], "2026-02-27", 240.0)
    assert p["PE"] == 20.0                      # 240 / TTM EPS 12
    assert p["EPS Growth %"] == 25.0            # FY25 10 vs FY24 8 (only 4 quarters reported)
    assert p["PEG"] == 0.8


def test_stock_with_no_reported_eps_gives_blank_pe_not_an_error():
    empty = {"annual_eps": {}, "quarterly_eps": {}}
    eps, basis = eps_ttm_at(empty, "2026-01-01")
    assert np.isnan(eps) and basis == "no EPS before this date"
    assert np.isnan(eps_growth_at(empty, "2026-01-01"))
    assert np.isnan(eps_ttm_at({"annual_eps": None, "quarterly_eps": {"2025-12-31": 2.0}}, "2026-01-01")[0])
    idx = pd.bdate_range("2025-06-01", "2026-02-27")
    hist = pd.DataFrame({"Close": np.linspace(100, 240, len(idx)), "Stock Splits": 0.0}, index=idx)
    p = parameters_at(empty, hist, hist["Close"], "2026-02-27", 240.0)
    assert np.isnan(p["PE"]) and np.isnan(p["PEG"]) and abs(p["Beta"] - 1) < 1e-9
