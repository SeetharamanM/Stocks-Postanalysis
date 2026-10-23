"""Streamlit app: when could each stock in my tradebooks have been sold for the most profit?

Run with:  streamlit run app.py
"""

from io import BytesIO
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from postanalysis.analysis import (
    analyse_lots, held_lots, pnl_totals, sold_lots, summarise_held, summarise_sold, totals_row,
)
from postanalysis.lots import adjust_for_splits, match_fifo
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

tickers = tuple(
    (isin, ticker_for(g["Symbol"].iloc[-1], set(g["Exchange"])))
    for isin, g in trades.groupby("ISIN")
)
histories = load_prices(tickers, trades["Trade Date"].min(), pd.Timestamp(as_of))
lots, unmatched = match_fifo(adjust_for_splits(trades, histories))
analysed = analyse_lots(lots, histories, as_of)

sold = sold_lots(analysed)
held = held_lots(analysed, as_of)
sold_summary = summarise_sold(sold)
held_summary = summarise_held(held)
sold_tot = pnl_totals(sold_summary, "Realised P&L")
held_tot = pnl_totals(held_summary, "Unrealised P&L")

def rupees(x: float) -> str:
    return f"-₹{abs(x):,.0f}" if x < 0 else f"₹{x:,.0f}"


def pct(x: float) -> str:
    return f"{x:+.1f}%"


def pnl_metrics(tot: dict, label: str):
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Invested", rupees(tot["Invested"]))
    m2.metric(f"Profit ({tot['Winners']} stocks)", rupees(tot["Profit"]),
              help="Sum of P&L of the stocks that made money")
    m3.metric(f"Loss ({tot['Losers']} stocks)", rupees(tot["Loss"]),
              help="Sum of P&L of the stocks that lost money")
    m4.metric(f"Net {label} P&L", rupees(tot["Net"]), pct(tot["Return %"]))


c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Trades", f"{len(trades):,}")
c2.metric("Files", trades["source_file"].nunique())
c3.metric("Stocks traded", trades["ISIN"].nunique())
c4.metric("Stocks sold", sold["ISIN"].nunique())
c5.metric("Stocks held", held["ISIN"].nunique())
o1, o2, o3, o4 = st.columns(4)
o1.metric("Total invested", rupees(sold_tot["Invested"] + held_tot["Invested"]),
          help="Cost of sold lots + cost of lots still held")
o2.metric("Realised P&L", rupees(sold_tot["Net"]), pct(sold_tot["Return %"]))
o3.metric("Unrealised P&L", rupees(held_tot["Net"]), pct(held_tot["Return %"]))
overall = sold_tot["Net"] + held_tot["Net"]
overall_inv = sold_tot["Invested"] + held_tot["Invested"]
o4.metric("Total P&L", rupees(overall), pct(overall / overall_inv * 100 if overall_inv else 0))
st.caption(
    f"Trades from {trades['Trade Date'].min():%d %b %Y} to {trades['Trade Date'].max():%d %b %Y}. "
    "P&L is before brokerage, STT, stamp duty, DP charges and tax. Best dates use daily closes, in hindsight. "
    "Quantities and prices are restated for later splits/bonuses."
)

money = {c: st.column_config.NumberColumn(format="₹%.0f") for c in
         ["Invested", "Actual P&L", "Realised P&L", "Unrealised P&L", "Best P&L", "Missed Profit"]}
price = {c: st.column_config.NumberColumn(format="%.2f") for c in
         ["Buy Price", "Avg Buy Price", "Exit Price", "Sell Price", "Best Sell Price", "Peak Price",
          "Price Now", "Actual Return %", "Best Return %", "Return %", "Since Sale %", "From Peak %"]}
qty = {c: st.column_config.NumberColumn(format="%g") for c in ["Quantity", "LTCG Qty"]}
dates = {c: st.column_config.DateColumn(format="DD MMM YYYY") for c in
         ["Buy Date", "Exit Date", "Best Sell Date", "Sell Date", "Last Sell Date", "Peak Date",
          "First Buy", "LTCG From", "Next LTCG Date"]}
fmt = {**money, **price, **dates, **qty}


def table(df: pd.DataFrame, cols: list[str], sort: str, ascending: bool, filename: str,
          sums: list[str] = (), unit: str = "stocks"):
    view = df[[c for c in cols if c in df.columns]]
    if sort in view:
        view = view.sort_values(sort, ascending=ascending)
    st.dataframe(view, hide_index=True, use_container_width=True, column_config=fmt)
    if sums and not view.empty:
        total_row = totals_row(view, list(sums), unit)
        total_row = total_row[[c for c in view.columns if c in total_row]]
        st.dataframe(total_row, hide_index=True, use_container_width=True, column_config=fmt)
        view = pd.concat([view, total_row], ignore_index=True)
    st.download_button("Download CSV", view.to_csv(index=False), filename, "text/csv", key=filename)


def total(df: pd.DataFrame, col: str) -> float:
    return df[col].sum() if col in df else 0.0


if not unmatched.empty:
    with st.expander(f"⚠️ {unmatched['Symbol'].nunique()} stocks sold with no matching buy — add older tradebooks"):
        st.write("These sells have no earlier buy in the loaded files, so they are left out of the analysis. "
                 "Usually shares from an IPO, demerger, transfer-in or a buy before your oldest tradebook: "
                 "add them as buy rows in a CSV in the tradebook folder (see README).")
        st.dataframe(unmatched, hide_index=True, use_container_width=True, column_config=fmt)

no_price = analysed.loc[analysed.get("Note", pd.Series(dtype=str)).eq("no price data"), "Symbol"].unique()
if len(no_price):
    st.warning(f"No price data for: {', '.join(sorted(no_price))}. "
               f"Add a CSV (Date, Close, High, Stock Splits) to {PRICE_CACHE} named <SYMBOL>.NS.csv.")

tab_sold, tab_held, tab_chart = st.tabs(["Sold stocks", "Held stocks", "Chart"])

with tab_sold:
    st.subheader("Sold: did I sell at the right time?")
    pnl_metrics(sold_tot, "realised")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Best possible P&L", rupees(total(sold, "Best P&L")))
    m2.metric("Missed profit", rupees(total(sold, "Missed Profit")))
    if "Since Sale %" in sold and sold["Since Sale %"].notna().any():
        m3.metric("Sold, then rose further", f"{(sold['Since Sale %'] > 0).mean():.0%} of lots")
    st.caption("Best date = highest close between buying and selling. "
               "Since Sale % = today's price vs your sell price (positive means it kept rising after you sold).")
    by_stock, by_lot = st.tabs(["By stock", "By lot"])
    with by_stock:
        table(sold_summary,
              ["Symbol", "Lots", "Quantity", "Invested", "Realised P&L", "Return %", "Best P&L", "Missed Profit",
               "Last Sell Date", "Price Now", "Since Sale %"],
              "Missed Profit", False, "sold_by_stock.csv",
              sums=["Lots", "Invested", "Realised P&L", "Best P&L", "Missed Profit"])
    with by_lot:
        table(sold,
              ["Symbol", "Quantity", "Buy Date", "Buy Price", "Invested", "Sell Date", "Sell Price", "Best Sell Date",
               "Best Sell Price", "Actual P&L", "Best P&L", "Missed Profit", "Actual Return %", "Best Return %",
               "Days Held", "Term", "Price Now", "Since Sale %", "Note"],
              "Missed Profit", False, "sold_lots.csv",
              sums=["Invested", "Actual P&L", "Best P&L", "Missed Profit"], unit="lots")

with tab_held:
    st.subheader("Held: how are my current holdings doing?")
    pnl_metrics(held_tot, "unrealised")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Current value", rupees(held_tot["Invested"] + held_tot["Net"]))
    m2.metric("P&L at each lot's peak", rupees(total(held, "Best P&L")))
    m3.metric("Lots turning LTCG in 30 days", int(((held["Days To LTCG"] > 0) & (held["Days To LTCG"] <= 30)).sum()))
    st.caption("Peak = highest close since you bought. From Peak % = today's price vs that peak. "
               "Lots held over 12 months are taxed as LTCG (12.5%) instead of STCG (20%).")
    by_stock, by_lot = st.tabs(["By stock", "By lot"])
    with by_stock:
        table(held_summary,
              ["Symbol", "Lots", "Quantity", "Avg Buy Price", "Invested", "Price Now", "Unrealised P&L", "Return %",
               "Peak Date", "Peak Price", "From Peak %", "Best P&L", "Missed Profit", "First Buy", "LTCG Qty",
               "Next LTCG Date"],
              "Unrealised P&L", True, "held_by_stock.csv",
              sums=["Lots", "Invested", "Unrealised P&L", "Best P&L", "Missed Profit"])
    with by_lot:
        table(held,
              ["Symbol", "Quantity", "Buy Date", "Buy Price", "Invested", "Price Now", "Actual P&L", "Actual Return %",
               "Best Sell Date", "Best Sell Price", "Best P&L", "From Peak %", "Days Held", "Term", "LTCG From",
               "Days To LTCG", "Note"],
              "Actual P&L", True, "held_lots.csv",
              sums=["Invested", "Actual P&L", "Best P&L"], unit="lots")

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
        st.caption("Chart and marker prices are adjusted for splits/bonuses.")
