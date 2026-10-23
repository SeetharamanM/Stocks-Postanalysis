import pandas as pd

from postanalysis.analysis import analyse_lots, held_lots, sold_lots, summarise_held, summarise_sold
from postanalysis.lots import adjust_for_splits, match_fifo
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


def test_bonus_shares_match_their_original_buy():
    # 1 share bought, 1:1 bonus on day 3, then 2 shares sold: no unmatched sell.
    t = trades([["ABC", "2026-06-01", "buy", 1, 200, 1], ["ABC", "2026-06-04", "sell", 2, 104, 2]])
    hist = history([100, 101, 102, 104, 106], [0, 0, 2.0, 0, 0])
    lots, unmatched = match_fifo(adjust_for_splits(t, {"INE000X01011": hist}))
    assert unmatched.empty
    out = analyse_lots(lots, {"INE000X01011": hist}).iloc[0]
    assert out["Quantity"] == 2 and out["Buy Price"] == 100
    assert out["Actual P&L"] == 8   # 2 x (104 - 100), not a 50% loss
    assert out["Best Sell Date"] == pd.Timestamp("2026-06-04")


def test_blank_isin_is_filled_from_same_symbol():
    df = pd.DataFrame([["ABC", "INE1", "2026-06-01", "buy", 1, 10, 1], ["ABC", "", "2026-06-02", "buy", 1, 10, 2]],
                      columns=["Symbol", "ISIN", "Trade Date", "Trade Type", "Quantity", "Price", "Trade ID"])
    df["Exchange"] = "NSE"
    assert normalise(df.astype(str))["ISIN"].tolist() == ["INE1", "INE1"]


def test_sold_and_held_are_analysed_separately():
    t = trades([
        ["ABC", "2026-06-01", "buy", 10, 100, 1],
        ["ABC", "2026-06-02", "buy", 5, 101, 2],
        ["ABC", "2026-06-04", "sell", 10, 105, 3],
    ])
    lots, _ = match_fifo(t)
    analysed = analyse_lots(lots, {"INE000X01011": history([100, 101, 112, 105, 108, 120])}, "2026-06-06")

    sold = sold_lots(analysed)
    assert sold["Quantity"].sum() == 10
    assert sold["Since Sale %"].iloc[0] == (120 / 105 - 1) * 100
    s = summarise_sold(sold).iloc[0]
    assert s["Realised P&L"] == 50 and s["Missed Profit"] == 70

    held = held_lots(analysed, "2026-06-06")
    assert held["Quantity"].sum() == 5
    assert held["Days To LTCG"].iloc[0] == 362  # LTCG from 3 Jun 2027
    h = summarise_held(held).iloc[0]
    assert h["Unrealised P&L"] == 5 * (120 - 101)
    assert h["Peak Date"] == pd.Timestamp("2026-06-06") and h["From Peak %"] == 0
    assert h["Next LTCG Date"] == pd.Timestamp("2027-06-03")
