"""Streamlit app: when could each stock in my tradebooks have been sold for the most profit?

Run with:  streamlit run app.py
"""

from io import BytesIO
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from postanalysis.analysis import analyse_lots, summarise_by_stock
from postanalysis.lots import match_fifo
from postanalysis.prices import get_history, ticker_for
from postanalysis.tradebook import load_folder, normalise, read_tradebook

ROOT = Path(__file__).parent
DEFAULT_FOLDER = ROOT / "data" / "tradebooks"
PRICE_CACHE = ROOT / "data" / "prices"

st.set_page_config(page_title="Stock Post-Analysis", layout="wide")
st.title("Stock post-analysis: best sell dates")

with st.sidebar:
    st.header("Tradebooks")
    folder = st.text_input("Folder with all tradebook files", str(DEFAULT_FOLDER))
    uploads = st.file_uploader("…or upload files", type=["xlsx", "xls", "csv"], accept_multiple_files=True)
    as_of = st.date_input("Analyse up to", pd.Timestamp.today())


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
    for i, (isin, ticker) in enumerate(tickers):
        try:
            out[isin] = get_history(ticker, start, end, PRICE_CACHE)
        except Exception:
            out[isin] = pd.DataFrame()
        progress.progress((i + 1) / len(tickers))
    progress.empty()
    return out


trades, errors = load_trades(folder, tuple((u.name, u.getvalue()) for u in uploads or []))
for err in errors:
    st.warning(err)
if trades.empty:
    st.info("Put your Zerodha Console tradebook exports in the folder above (or upload them).")
    st.stop()

lots, unmatched = match_fifo(trades)
tickers = tuple(
    (isin, ticker_for(g["Symbol"].iloc[-1], set(g["Exchange"])))
    for isin, g in trades.groupby("ISIN")
)
histories = load_prices(tickers, trades["Trade Date"].min(), pd.Timestamp(as_of))
analysed = analyse_lots(lots, histories, as_of)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Trades", f"{len(trades):,}")
c2.metric("Files", trades["source_file"].nunique())
c3.metric("Stocks", trades["ISIN"].nunique())
if "Best P&L" in analysed:
    c4.metric("Actual P&L", f"₹{analysed['Actual P&L'].sum():,.0f}")
    c5.metric("Best possible P&L", f"₹{analysed['Best P&L'].sum():,.0f}",
              f"₹{analysed['Missed Profit'].sum():,.0f} missed", delta_color="off")
st.caption(
    f"Trades from {trades['Trade Date'].min():%d %b %Y} to {trades['Trade Date'].max():%d %b %Y}. "
    "P&L is before brokerage, STT, stamp duty, DP charges and tax. Best dates use daily closes, in hindsight."
)

money = {c: st.column_config.NumberColumn(format="₹%.0f") for c in
         ["Invested", "Actual P&L", "Best P&L", "Missed Profit"]}
price = {c: st.column_config.NumberColumn(format="%.2f") for c in
         ["Buy Price", "Exit Price", "Best Sell Price", "Sell Price", "Actual Return %", "Best Return %"]}
dates = {c: st.column_config.DateColumn(format="DD MMM YYYY") for c in
         ["Buy Date", "Exit Date", "Best Sell Date", "Sell Date", "Latest Best Date"]}

if not unmatched.empty:
    with st.expander(f"⚠️ {unmatched['Symbol'].nunique()} stocks sold with no matching buy — add older tradebooks"):
        st.write("These sells have no earlier buy in the loaded files, so they are left out of the analysis.")
        st.dataframe(unmatched, hide_index=True, use_container_width=True, column_config=dates)

no_price = analysed.loc[analysed.get("Note", pd.Series(dtype=str)).eq("no price data"), "Symbol"].unique()
if len(no_price):
    st.warning(f"No price data for: {', '.join(sorted(no_price))}. "
               f"Add a CSV (Date, Close, High, Stock Splits) to {PRICE_CACHE} named <SYMBOL>.NS.csv.")

tab_stock, tab_lots, tab_chart = st.tabs(["By stock", "By lot", "Chart"])

with tab_stock:
    status = st.radio("Show", ["All", "Sold", "Held"], horizontal=True)
    summary = summarise_by_stock(analysed)
    if status != "All" and not summary.empty:
        summary = summary[summary["Status"] == status]
    st.dataframe(summary, hide_index=True, use_container_width=True, column_config={**money, **dates})

with tab_lots:
    cols = ["Symbol", "Status", "Quantity", "Buy Date", "Buy Price", "Exit Date", "Exit Price",
            "Best Sell Date", "Best Sell Price", "Actual P&L", "Best P&L", "Missed Profit",
            "Actual Return %", "Best Return %", "Days Held", "Term", "Note"]
    view = analysed[[c for c in cols if c in analysed.columns]].sort_values("Missed Profit", ascending=False)
    st.dataframe(view, hide_index=True, use_container_width=True, column_config={**money, **price, **dates})
    st.download_button("Download CSV", view.to_csv(index=False), "best_sell_dates.csv", "text/csv")

with tab_chart:
    symbols = sorted(analysed["Symbol"].unique())
    symbol = st.selectbox("Stock", symbols)
    isin = analysed.loc[analysed["Symbol"] == symbol, "ISIN"].iloc[0]
    hist = histories.get(isin, pd.DataFrame())
    if hist.empty:
        st.info("No price data for this stock.")
    else:
        sel = analysed[analysed["Symbol"] == symbol]
        fig = go.Figure(go.Scatter(x=hist.index, y=hist["Close"], name="Close", line=dict(color="#4c78a8")))
        fig.add_scatter(x=sel["Buy Date"], y=sel["Buy Price"], mode="markers", name="Buy",
                        marker=dict(color="#2ca02c", size=10, symbol="triangle-up"))
        sold = sel[sel["Status"] == "Sold"]
        fig.add_scatter(x=sold["Sell Date"], y=sold["Sell Price"], mode="markers", name="Actual sell",
                        marker=dict(color="#d62728", size=10, symbol="triangle-down"))
        if "Best Sell Date" in sel:
            fig.add_scatter(x=sel["Best Sell Date"], y=sel["Best Sell Price"], mode="markers", name="Best sell",
                            marker=dict(color="#ff7f0e", size=12, symbol="star"))
        fig.update_layout(height=480, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Buy/sell markers show traded prices; if the stock split, chart prices are split-adjusted.")
