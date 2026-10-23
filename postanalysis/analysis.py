"""Hindsight analysis: for every lot, the best date it could have been sold on."""

import pandas as pd

from .prices import split_factor_after

LTCG_DAYS = 365


def analyse_lots(lots: pd.DataFrame, histories: dict[str, pd.DataFrame], as_of=None) -> pd.DataFrame:
    """Add best-sell-date and profit columns to `lots`.

    `histories` maps ISIN -> daily prices (split-adjusted to today's share count).
    Lot prices are rescaled into the same basis so splits/bonuses don't look like crashes.
    The search window runs from the day after purchase to the actual sell date, or to the
    last available price for lots still held.
    """
    as_of = pd.Timestamp(as_of or pd.Timestamp.today()).normalize()
    rows = []
    for lot in lots.to_dict("records"):
        hist = histories.get(lot["ISIN"])
        out = dict(lot)
        out.update({"Status": "Sold" if pd.notna(lot["Sell Date"]) else "Held"})
        if hist is None or hist.empty:
            out["Note"] = "no price data"
            rows.append(out)
            continue

        buy_factor = split_factor_after(hist, lot["Buy Date"])
        buy_price = lot["Buy Price"] / buy_factor
        qty = lot["Quantity"] * buy_factor
        if out["Status"] == "Sold":
            end = lot["Sell Date"]
            exit_date, exit_price = end, lot["Sell Price"] / split_factor_after(hist, end)
        else:
            end = min(as_of, hist.index.max())
            exit_date, exit_price = hist.index.max(), hist["Close"].iloc[-1]

        window = hist.loc[(hist.index > lot["Buy Date"]) & (hist.index <= end), "Close"].dropna()
        if window.empty:
            out["Note"] = "sold same day (intraday)" if out["Status"] == "Sold" else "no prices after buy date"
            out.update({"Exit Date": exit_date, "Exit Price": exit_price,
                        "Actual P&L": (exit_price - buy_price) * qty})
            rows.append(out)
            continue

        best_date = window.idxmax()
        best_price = window.loc[best_date]
        actual = (exit_price - buy_price) * qty
        best = (best_price - buy_price) * qty
        out.update({
            "Exit Date": exit_date,
            "Exit Price": exit_price,
            "Actual P&L": actual,
            "Best Sell Date": best_date,
            "Best Sell Price": best_price,
            "Best P&L": best,
            "Missed Profit": best - actual,
            "Actual Return %": (exit_price / buy_price - 1) * 100,
            "Best Return %": (best_price / buy_price - 1) * 100,
            "Days Held": (exit_date - lot["Buy Date"]).days,
            "Term": "LTCG" if (exit_date - lot["Buy Date"]).days > LTCG_DAYS else "STCG",
            "Note": "split/bonus adjusted" if buy_factor != 1 else "",
        })
        rows.append(out)
    return pd.DataFrame(rows)


def summarise_by_stock(analysed: pd.DataFrame) -> pd.DataFrame:
    if analysed.empty or "Best P&L" not in analysed:
        return pd.DataFrame()
    g = analysed.dropna(subset=["Best P&L"]).groupby(["Symbol", "Status"], as_index=False)
    out = g.agg(
        Lots=("Quantity", "size"),
        Quantity=("Quantity", "sum"),
        Invested=("Buy Price", lambda s: (s * analysed.loc[s.index, "Quantity"]).sum()),
        Actual_PnL=("Actual P&L", "sum"),
        Best_PnL=("Best P&L", "sum"),
        Missed=("Missed Profit", "sum"),
        Best_Date=("Best Sell Date", "max"),
    )
    out.columns = ["Symbol", "Status", "Lots", "Quantity", "Invested", "Actual P&L", "Best P&L", "Missed Profit", "Latest Best Date"]
    return out.sort_values("Missed Profit", ascending=False).reset_index(drop=True)
