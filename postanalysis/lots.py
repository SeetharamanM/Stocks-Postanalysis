"""FIFO matching of buys and sells into lots (how Indian capital-gains tax matches them)."""

from collections import deque

import pandas as pd

LOT_COLUMNS = ["Symbol", "ISIN", "Exchange", "Quantity", "Buy Date", "Buy Price", "Sell Date", "Sell Price"]


def match_fifo(trades: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (lots, unmatched_sells).

    Each lot is a quantity bought on one date; `Sell Date` is NaT while it is still held.
    Sells with no earlier buy in the loaded files land in `unmatched_sells`; they mean
    an older tradebook (or opening holdings) is missing from the folder.
    """
    lots, unmatched = [], []
    trades = _for_itertuples(trades)
    # Group by ISIN: NSE and BSE trades of the same stock share one demat holding.
    for isin, group in trades.groupby("ISIN", sort=False):
        queue: deque[dict] = deque()
        for t in group.itertuples(index=False):
            row = t._asdict()
            qty = row["Quantity"]
            if row["Trade_Type"] == "buy":
                queue.append({
                    "Symbol": row["Symbol"], "ISIN": isin, "Exchange": row["Exchange"],
                    "Quantity": qty, "Buy Date": row["Trade_Date"], "Buy Price": row["Price"],
                })
                continue
            while qty > 0 and queue:
                lot = queue[0]
                take = min(qty, lot["Quantity"])
                lots.append({**lot, "Quantity": take, "Sell Date": row["Trade_Date"], "Sell Price": row["Price"]})
                lot["Quantity"] -= take
                qty -= take
                if lot["Quantity"] == 0:
                    queue.popleft()
            if qty > 0:
                unmatched.append({
                    "Symbol": row["Symbol"], "ISIN": isin, "Exchange": row["Exchange"],
                    "Quantity": qty, "Sell Date": row["Trade_Date"], "Sell Price": row["Price"],
                })
        for lot in queue:
            lots.append({**lot, "Sell Date": pd.NaT, "Sell Price": float("nan")})

    lots_df = pd.DataFrame(lots, columns=LOT_COLUMNS)
    unmatched_df = pd.DataFrame(unmatched, columns=["Symbol", "ISIN", "Exchange", "Quantity", "Sell Date", "Sell Price"])
    return lots_df, unmatched_df


def _for_itertuples(trades: pd.DataFrame) -> pd.DataFrame:
    """Rename columns so itertuples() exposes them as attributes."""
    return trades.rename(columns={"Trade Type": "Trade_Type", "Trade Date": "Trade_Date"})[
        ["Symbol", "ISIN", "Exchange", "Trade_Type", "Trade_Date", "Quantity", "Price"]
    ]
