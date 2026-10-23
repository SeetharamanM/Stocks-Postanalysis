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
        buy_price, qty = lot["Buy Price"], lot["Quantity"]
        if hist is None or hist.empty:
            out["Note"] = "no price data"
            if out["Status"] == "Sold":  # realised P&L needs no market prices
                out.update(_exit_columns(lot, lot["Sell Date"], lot["Sell Price"]))
            rows.append(out)
            continue

        if out["Status"] == "Sold":
            end = lot["Sell Date"]
            exit_date, exit_price = end, lot["Sell Price"]
        else:
            end = min(as_of, hist.index.max())
            exit_date, exit_price = hist.index.max(), hist["Close"].iloc[-1]

        window = hist.loc[(hist.index > lot["Buy Date"]) & (hist.index <= end), "Close"].dropna()
        if window.empty:
            out.update(_exit_columns(lot, exit_date, exit_price))
            out["Price Now"] = hist["Close"].iloc[-1]
            if out["Status"] == "Sold":
                # Sold before the next close: the sale itself is the only possible exit.
                out.update({"Note": "sold same day (intraday)", "Best Sell Date": exit_date,
                            "Best Sell Price": exit_price, "Best P&L": out["Actual P&L"], "Missed Profit": 0.0,
                            "Best Return %": out["Actual Return %"]})
            else:
                out["Note"] = "no prices after buy date"
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


def _exit_columns(lot: dict, exit_date, exit_price) -> dict:
    held_days = (exit_date - lot["Buy Date"]).days
    return {
        "Exit Date": exit_date,
        "Exit Price": exit_price,
        "Actual P&L": (exit_price - lot["Buy Price"]) * lot["Quantity"],
        "Actual Return %": (exit_price / lot["Buy Price"] - 1) * 100,
        "Days Held": held_days,
        "Term": "LTCG" if held_days > LTCG_DAYS else "STCG",
    }


def sold_lots(analysed: pd.DataFrame) -> pd.DataFrame:
    """Closed lots, plus how the price moved after the sale."""
    sold = analysed[analysed["Status"] == "Sold"].copy()
    sold["Invested"] = _invested(sold)
    if "Price Now" in sold:
        sold["Since Sale %"] = (sold["Price Now"] / sold["Sell Price"] - 1) * 100
    return sold


def held_lots(analysed: pd.DataFrame, as_of=None) -> pd.DataFrame:
    """Open lots, plus distance from their peak and when they turn long-term."""
    as_of = pd.Timestamp(as_of or pd.Timestamp.today()).normalize()
    held = analysed[analysed["Status"] == "Held"].copy()
    held["Invested"] = _invested(held)
    if "Best Sell Price" in held:
        held["From Peak %"] = (held["Exit Price"] / held["Best Sell Price"] - 1) * 100
    held["LTCG From"] = held["Buy Date"] + pd.Timedelta(days=LTCG_DAYS + 1)
    held["Days To LTCG"] = (held["LTCG From"] - as_of).dt.days.clip(lower=0)
    return held


PRICE_COLUMNS = ["Price Now", "Exit Price", "Best Sell Date", "Best Sell Price", "Best P&L", "Missed Profit"]


def _with_price_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lots without any price data lack these columns; add them as empty so summaries still work."""
    return df.reindex(columns=df.columns.union(PRICE_COLUMNS, sort=False))


def _invested(df: pd.DataFrame) -> pd.Series:
    return df["Buy Price"] * df["Quantity"]


def summarise_sold(sold: pd.DataFrame) -> pd.DataFrame:
    """One row per stock: realised P&L vs the best it could have been."""
    sold = _with_price_columns(sold).dropna(subset=["Actual P&L"])
    if sold.empty:
        return pd.DataFrame()
    sold = sold.assign(Proceeds=sold["Sell Price"] * sold["Quantity"])
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
    held = _with_price_columns(held).dropna(subset=["Actual P&L"])
    if held.empty:
        return pd.DataFrame()
    held = held.assign(LTCG_Qty=held["Quantity"].where(held["Term"] == "LTCG", 0))
    priced = held.dropna(subset=["Best Sell Price"])
    peak = priced.loc[priced.groupby("Symbol")["Best Sell Price"].idxmax(), ["Symbol", "Best Sell Date", "Best Sell Price"]]
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


def pnl_totals(summary: pd.DataFrame, pnl_col: str) -> dict:
    """Invested, gross profit (winning stocks), gross loss (losing stocks) and net P&L of a per-stock summary."""
    if summary.empty:
        return {"Invested": 0.0, "Profit": 0.0, "Loss": 0.0, "Net": 0.0, "Winners": 0, "Losers": 0, "Return %": 0.0}
    pnl = summary[pnl_col]
    invested = summary["Invested"].sum()
    return {
        "Invested": invested,
        "Profit": pnl[pnl > 0].sum(),
        "Loss": pnl[pnl < 0].sum(),
        "Net": pnl.sum(),
        "Winners": int((pnl > 0).sum()),
        "Losers": int((pnl < 0).sum()),
        "Return %": pnl.sum() / invested * 100 if invested else 0.0,
    }


def totals_row(summary: pd.DataFrame, sum_cols: list[str], unit: str = "stocks") -> pd.DataFrame:
    """A single 'Total' row summing `sum_cols`, with Return % recomputed on the totals."""
    row = {c: summary[c].sum() for c in sum_cols if c in summary}
    row["Symbol"] = f"Total ({len(summary)} {unit})"
    pnl = next((c for c in ["Realised P&L", "Unrealised P&L", "Actual P&L"] if c in row), None)
    if pnl and row.get("Invested"):
        row["Return %"] = row[pnl] / row["Invested"] * 100
    return pd.DataFrame([row])
