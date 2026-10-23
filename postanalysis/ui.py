"""Streamlit pieces shared by the app's pages: sidebar, cached data pipeline, formatted tables."""

from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from .analysis import analyse_lots, totals_row
from .formatting import inr
from .lots import adjust_for_splits, match_fifo
from .prices import get_history, ticker_for
from .tradebook import load_folder, normalise, read_tradebook

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FOLDER = ROOT / "data" / "tradebooks"
PRICE_CACHE = ROOT / "data" / "prices"
FUNDAMENTALS_CACHE = ROOT / "data" / "fundamentals"

MONEY = {"Invested", "Actual P&L", "Realised P&L", "Unrealised P&L", "Best P&L", "Missed Profit", "Sale Value",
         "Profit", "Loss", "Net P&L", "STCG P&L", "LTCG P&L", "Current Value"}
PRICES = {"Buy Price", "Avg Buy Price", "Exit Price", "Sell Price", "Best Sell Price", "Peak Price", "Price Now",
          "Traded Price", "EPS (TTM)"}
RATIOS = {"PE", "PEG", "Beta", "PE Now", "PEG Now"}
QTY = {"Quantity", "LTCG Qty", "Lots", "Stocks", "Days Held", "Days To LTCG"}


def sidebar(allow_upload: bool = False):
    """Tradebook folder, optional uploads and as-of date, remembered across pages."""
    state = st.session_state
    state.setdefault("folder", str(DEFAULT_FOLDER))
    state.setdefault("as_of", pd.Timestamp.today().date())
    state.setdefault("uploads", ())
    with st.sidebar:
        st.header("Tradebooks")
        state["folder"] = st.text_input("Folder with all tradebook files", state["folder"])
        if allow_upload:
            files = st.file_uploader("…or upload files", type=["xlsx", "xls", "csv"], accept_multiple_files=True)
            state["uploads"] = tuple((f.name, f.getvalue()) for f in files or [])
        elif state["uploads"]:
            st.caption(f"Using {len(state['uploads'])} uploaded file(s) from the main page.")
        state["as_of"] = st.date_input("Analyse up to", state["as_of"])
    return state["folder"], state["uploads"], pd.Timestamp(state["as_of"])


@st.cache_data(show_spinner="Reading tradebooks…")
def load_trades(folder: str, uploaded: tuple) -> tuple[pd.DataFrame, list[str]]:
    trades, errors = load_folder(folder) if Path(folder).expanduser().is_dir() else (pd.DataFrame(), [])
    frames = [trades] if not trades.empty else []
    for name, data in uploaded:
        try:
            frames.append(read_tradebook(BytesIO(data), name))
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    if not frames:
        return pd.DataFrame(), errors
    return normalise(pd.concat(frames, ignore_index=True)), errors


@st.cache_data(show_spinner="Fetching price history (cached after first run)…")
def load_prices(tickers: tuple, start, end) -> dict[str, pd.DataFrame]:
    out = {}
    progress = st.progress(0.0)
    for i, (key, ticker) in enumerate(tickers):
        try:
            out[key] = get_history(ticker, start, end, PRICE_CACHE)
        except Exception:
            out[key] = pd.DataFrame()
        progress.progress((i + 1) / len(tickers))
    progress.empty()
    return out


def tickers_for(trades: pd.DataFrame) -> dict[str, str]:
    """ISIN -> Yahoo ticker."""
    return {isin: ticker_for(g["Symbol"].iloc[-1], set(g["Exchange"])) for isin, g in trades.groupby("ISIN")}


def load_all(folder: str, uploads: tuple, as_of: pd.Timestamp):
    """Trades -> prices -> split-adjusted FIFO lots -> per-lot analysis. Stops the page if nothing loaded."""
    trades, errors = load_trades(folder, uploads)
    for err in errors:
        st.warning(err)
    if trades.empty:
        st.info("Put your Zerodha Console tradebook exports in the folder in the sidebar (or upload them).")
        st.stop()
    histories = load_prices(tuple(tickers_for(trades).items()), trades["Trade Date"].min(), as_of)
    lots, unmatched = match_fifo(adjust_for_splits(trades, histories))
    return trades, histories, analyse_lots(lots, histories, as_of), unmatched


def _fmt(col: str):
    if col in MONEY:
        return inr
    if col in PRICES:
        return lambda v: inr(v, 2, symbol=False)
    if col.endswith("%"):
        return lambda v: "" if pd.isna(v) else f"{v:,.2f}"
    if col in RATIOS:
        return lambda v: "" if pd.isna(v) else f"{v:,.2f}"
    if col in QTY:
        return lambda v: "" if pd.isna(v) else inr(v, 0 if float(v).is_integer() else 2, symbol=False)
    return None


def show(df: pd.DataFrame, **kwargs):
    """st.dataframe with Indian-format amounts; sorting still uses the underlying numbers."""
    formats = {c: f for c in df.columns if (f := _fmt(c))}
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            pattern = "%b %Y" if c == "Month" else "%d %b %Y"
            formats[c] = lambda v, p=pattern: "" if pd.isna(v) else v.strftime(p)
    # One format() call: a second call would reset every column it doesn't list to the default.
    st.dataframe(df.style.format(formats, na_rep=""), hide_index=True, use_container_width=True, **kwargs)


def table(df: pd.DataFrame, cols: list[str], sort: str, ascending: bool, filename: str,
          sums: list[str] = (), unit: str = "stocks", label_col: str = "Symbol"):
    view = df[[c for c in cols if c in df.columns]]
    if sort in view:
        view = view.sort_values(sort, ascending=ascending)
    show(view)
    if sums and not view.empty:
        total_row = totals_row(view, list(sums), unit, label_col)
        total_row = total_row[[c for c in view.columns if c in total_row]]
        show(total_row)
        view = pd.concat([view, total_row], ignore_index=True)
    st.download_button("Download CSV", view.to_csv(index=False), filename, "text/csv", key=filename)
