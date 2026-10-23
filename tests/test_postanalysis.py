import pandas as pd

from postanalysis.analysis import analyse_lots
from postanalysis.lots import match_fifo
from postanalysis.tradebook import normalise


def trades(rows):
    df = pd.DataFrame(rows, columns=["Symbol", "Trade Date", "Trade Type", "Quantity", "Price", "Trade ID"])
    df["ISIN"] = "INE000X01011"
    df["Exchange"] = "NSE"
    return normalise(df.astype(str))


def history(prices, splits=None):
    idx = pd.date_range("2026-06-01", periods=len(prices), freq="D")
    return pd.DataFrame({"Close": prices, "High": prices, "Stock Splits": splits or [0.0] * len(prices)}, index=idx)


def test_fifo_matches_oldest_buy_first_and_reports_unmatched_sells():
    t = trades([
        ["ABC", "2026-06-01", "buy", 2, 100, 1],
        ["ABC", "2026-06-03", "buy", 3, 110, 2],
        ["ABC", "2026-06-05", "sell", 4, 120, 3],
        ["ABC", "2026-06-06", "sell", 2, 125, 4],
    ])
    lots, unmatched = match_fifo(t)
    assert list(lots["Quantity"]) == [2, 2, 1]
    assert list(lots["Buy Price"]) == [100, 110, 110]
    assert lots["Sell Date"].notna().all()
    assert unmatched["Quantity"].tolist() == [1]


def test_duplicate_trades_across_files_are_dropped():
    row = ["ABC", "2026-06-01", "buy", 1, 100, 7]
    assert len(trades([row, row])) == 1


def test_best_sell_date_within_holding_window():
    t = trades([["ABC", "2026-06-01", "buy", 10, 100, 1], ["ABC", "2026-06-04", "sell", 10, 105, 2]])
    lots, _ = match_fifo(t)
    # Day 6 has the highest close but is after the sale, so it must be ignored.
    out = analyse_lots(lots, {"INE000X01011": history([100, 103, 112, 104, 108, 130])}).iloc[0]
    assert out["Best Sell Date"] == pd.Timestamp("2026-06-03")
    assert out["Actual P&L"] == 50
    assert out["Best P&L"] == 120
    assert out["Missed Profit"] == 70


def test_split_after_purchase_is_not_a_crash():
    t = trades([["ABC", "2026-06-01", "buy", 1, 200, 1]])
    lots, _ = match_fifo(t)
    # 1:2 split on day 3; Yahoo closes are already split-adjusted.
    out = analyse_lots(lots, {"INE000X01011": history([100, 101, 102, 104], [0, 0, 2.0, 0])}, "2026-06-04").iloc[0]
    assert out["Status"] == "Held"
    assert out["Best P&L"] == 8   # 2 shares x (104 - 100)
    assert out["Note"] == "split/bonus adjusted"
