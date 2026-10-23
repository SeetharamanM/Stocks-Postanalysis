"""Hindsight analysis: for every lot, the best date it could have been sold on."""

import pandas as pd

LTCG_DAYS = 365


def analyse_lots(lots: pd.DataFrame, histories: dict[str, pd.DataFrame], as_of=None) -> pd.DataFrame:
    """Add best-sell-date and profit columns to `lots`.

    `histories` maps ISIN -> daily prices (split-adjusted to today's share count); lots
    should come from trades passed through `adjust_for_splits` so both use the same basis.
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

        buy_price, qty = lot["Buy Price"], lot["Quantity"]
        if out["Status"] == "Sold":
            end = lot["Sell Date"]
            exit_date, exit_price = end, lot["Sell Price"]
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
            "Price Now": hist["Close"].iloc[-1],
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
            "Note": "",
        })
        rows.append(out)
    return pd.DataFrame(rows)


def sold_lots(analysed: pd.DataFrame) -> pd.DataFrame:
    """Closed lots, plus how the price moved after the sale."""
    sold = analysed[analysed["Status"] == "Sold"].copy()
    if "Price Now" in sold:
        sold["Since Sale %"] = (sold["Price Now"] / sold["Sell Price"] - 1) * 100
    return sold


def held_lots(analysed: pd.DataFrame, as_of=None) -> pd.DataFrame:
    """Open lots, plus distance from their peak and when they turn long-term."""
    as_of = pd.Timestamp(as_of or pd.Timestamp.today()).normalize()
    held = analysed[analysed["Status"] == "Held"].copy()
    if "Best Sell Price" in held:
        held["From Peak %"] = (held["Exit Price"] / held["Best Sell Price"] - 1) * 100
    held["LTCG From"] = held["Buy Date"] + pd.Timedelta(days=LTCG_DAYS + 1)
    held["Days To LTCG"] = (held["LTCG From"] - as_of).dt.days.clip(lower=0)
    return held


def _invested(df: pd.DataFrame) -> pd.Series:
    return df["Buy Price"] * df["Quantity"]


def summarise_sold(sold: pd.DataFrame) -> pd.DataFrame:
    """One row per stock: realised P&L vs the best it could have been."""
    sold = sold.dropna(subset=["Best P&L"])
    if sold.empty:
        return pd.DataFrame()
    sold = sold.assign(Invested=_invested(sold), Proceeds=sold["Sell Price"] * sold["Quantity"])
    out = sold.groupby("Symbol").agg(
        Lots=("Quantity", "size"),
        Quantity=("Quantity", "sum"),
        Invested=("Invested", "sum"),
        Proceeds=("Proceeds", "sum"),
        **{"Realised P&L": ("Actual P&L", "sum"),
           "Best P&L": ("Best P&L", "sum"),
           "Missed Profit": ("Missed Profit", "sum"),
           "Last Sell Date": ("Sell Date", "max"),
           "Price Now": ("Price Now", "last")},
    )
    out["Return %"] = out["Realised P&L"] / out["Invested"] * 100
    out["Since Sale %"] = (out["Price Now"] / (out["Proceeds"] / out["Quantity"]) - 1) * 100
    out = out.drop(columns="Proceeds")
    return out.sort_values("Missed Profit", ascending=False).reset_index()


def summarise_held(held: pd.DataFrame) -> pd.DataFrame:
    """One row per stock still held: unrealised P&L, peak since buying, and tax timing."""
    held = held.dropna(subset=["Best P&L"])
    if held.empty:
        return pd.DataFrame()
    held = held.assign(Invested=_invested(held), LTCG_Qty=held["Quantity"].where(held["Term"] == "LTCG", 0))
    peak = held.loc[held.groupby("Symbol")["Best Sell Price"].idxmax(), ["Symbol", "Best Sell Date", "Best Sell Price"]]
    pending = held[held["Days To LTCG"] > 0].groupby("Symbol")["LTCG From"].min()
    out = held.groupby("Symbol").agg(
        Lots=("Quantity", "size"),
        Quantity=("Quantity", "sum"),
        Invested=("Invested", "sum"),
        **{"Price Now": ("Exit Price", "last"),
           "Unrealised P&L": ("Actual P&L", "sum"),
           "Best P&L": ("Best P&L", "sum"),
           "Missed Profit": ("Missed Profit", "sum"),
           "First Buy": ("Buy Date", "min"),
           "LTCG Qty": ("LTCG_Qty", "sum")},
    )
    out["Avg Buy Price"] = out["Invested"] / out["Quantity"]
    out["Return %"] = out["Unrealised P&L"] / out["Invested"] * 100
    out = out.join(peak.set_index("Symbol").rename(columns={"Best Sell Date": "Peak Date", "Best Sell Price": "Peak Price"}))
    out["From Peak %"] = (out["Price Now"] / out["Peak Price"] - 1) * 100
    out["Next LTCG Date"] = pending
    cols = ["Lots", "Quantity", "Avg Buy Price", "Invested", "Price Now", "Unrealised P&L", "Return %",
            "Peak Date", "Peak Price", "From Peak %", "Best P&L", "Missed Profit", "First Buy", "LTCG Qty", "Next LTCG Date"]
    return out[cols].sort_values("Unrealised P&L").reset_index()
