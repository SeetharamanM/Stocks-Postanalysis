"""Sell analysis page: when could each stock in my tradebooks have been sold for the most profit?"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from postanalysis.analysis import (
    held_lots, monthly_realised, pnl_totals, sold_lots, summarise_held, summarise_sold, yearly_realised,
)
from postanalysis.formatting import inr, inr_short
from postanalysis.ui import PRICE_CACHE, load_all, show, sidebar, table

st.title("Stock post-analysis: best sell dates")

folder, uploads, as_of = sidebar(allow_upload=True)
trades, histories, analysed, unmatched = load_all(folder, uploads, as_of)

sold = sold_lots(analysed)
held = held_lots(analysed, as_of)
sold_summary = summarise_sold(sold)
held_summary = summarise_held(held)
sold_tot = pnl_totals(sold_summary, "Realised P&L")
held_tot = pnl_totals(held_summary, "Unrealised P&L")


def pct(x: float) -> str:
    return f"{x:+.1f}%"


def money_metric(col, label: str, value: float, delta=None, **kwargs):
    """Full Indian-format amount, with the lakh/crore short form on hover."""
    col.metric(label, inr(value), delta, help=kwargs.pop("help", None) or inr_short(value), **kwargs)


def pnl_metrics(tot: dict, label: str):
    m1, m2, m3, m4 = st.columns(4)
    money_metric(m1, "Invested", tot["Invested"])
    money_metric(m2, f"Profit ({tot['Winners']} stocks)", tot["Profit"],
                 help="Sum of P&L of the stocks that made money")
    money_metric(m3, f"Loss ({tot['Losers']} stocks)", tot["Loss"],
                 help="Sum of P&L of the stocks that lost money")
    money_metric(m4, f"Net {label} P&L", tot["Net"], pct(tot["Return %"]))


c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Trades", inr(len(trades), symbol=False))
c2.metric("Files", trades["source_file"].nunique())
c3.metric("Stocks traded", trades["ISIN"].nunique())
c4.metric("Stocks sold", sold["ISIN"].nunique())
c5.metric("Stocks held", held["ISIN"].nunique())
o1, o2, o3, o4 = st.columns(4)
overall_inv = sold_tot["Invested"] + held_tot["Invested"]
overall = sold_tot["Net"] + held_tot["Net"]
money_metric(o1, "Total invested", overall_inv, help="Cost of sold lots + cost of lots still held")
money_metric(o2, "Realised P&L", sold_tot["Net"], pct(sold_tot["Return %"]))
money_metric(o3, "Unrealised P&L", held_tot["Net"], pct(held_tot["Return %"]))
money_metric(o4, "Total P&L", overall, pct(overall / overall_inv * 100 if overall_inv else 0))
st.caption(
    f"Trades from {trades['Trade Date'].min():%d %b %Y} to {trades['Trade Date'].max():%d %b %Y}. "
    "P&L is before brokerage, STT, stamp duty, DP charges and tax. Best dates use daily closes, in hindsight. "
    "Quantities and prices are restated for later splits/bonuses."
)
st.page_link("views/stock_parameters.py", label="PE, PEG and alpha of each stock at its peak →", icon="📊")


def total(df: pd.DataFrame, col: str) -> float:
    return df[col].sum() if col in df else 0.0


if not unmatched.empty:
    with st.expander(f"⚠️ {unmatched['Symbol'].nunique()} stocks sold with no matching buy — add older tradebooks"):
        st.write("These sells have no earlier buy in the loaded files, so they are left out of the analysis. "
                 "Usually shares from an IPO, demerger, transfer-in or a buy before your oldest tradebook: "
                 "add them as buy rows in a CSV in the tradebook folder (see README).")
        show(unmatched)

no_price = analysed.loc[analysed.get("Note", pd.Series(dtype=str)).eq("no price data"), "Symbol"].unique()
if len(no_price):
    st.warning(f"No price data for: {', '.join(sorted(no_price))}. "
               f"Add a CSV (Date, Close, High, Stock Splits) to {PRICE_CACHE} named <SYMBOL>.NS.csv.")

tab_sold, tab_held, tab_month, tab_chart = st.tabs(["Sold stocks", "Held stocks", "Monthly P&L", "Chart"])

with tab_sold:
    st.subheader("Sold: did I sell at the right time?")
    pnl_metrics(sold_tot, "realised")
    m1, m2, m3, m4 = st.columns(4)
    money_metric(m1, "Best possible P&L", total(sold, "Best P&L"))
    money_metric(m2, "Missed profit", total(sold, "Missed Profit"))
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
    money_metric(m1, "Current value", held_tot["Invested"] + held_tot["Net"])
    money_metric(m2, "P&L at each lot's peak", total(held, "Best P&L"))
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

with tab_month:
    st.subheader("Monthly P&L: realised profit and loss by month of sale")
    monthly = monthly_realised(sold)
    if monthly.empty:
        st.info("No sold lots yet.")
    else:
        years = ["All years", *sorted(monthly["FY"].unique(), reverse=True)]
        fy = st.selectbox("Financial year (April–March)", years)
        view = monthly if fy == "All years" else monthly[monthly["FY"] == fy]

        m1, m2, m3, m4, m5 = st.columns(5)
        money_metric(m1, "Profit", view["Profit"].sum())
        money_metric(m2, "Loss", view["Loss"].sum())
        net, inv = view["Net P&L"].sum(), view["Invested"].sum()
        money_metric(m3, "Net realised P&L", net, pct(net / inv * 100 if inv else 0))
        best = view.loc[view["Net P&L"].idxmax()]
        worst = view.loc[view["Net P&L"].idxmin()]
        m4.metric("Best month", f"{best['Month']:%b %Y}", inr(best["Net P&L"]))
        m5.metric("Worst month", f"{worst['Month']:%b %Y}", inr(worst["Net P&L"]))

        labels = view["Month"].dt.strftime("%b %Y")
        fig = go.Figure()
        fig.add_bar(x=labels, y=view["Profit"], name="Profit", marker_color="#2ca02c",
                    customdata=view["Profit"].map(inr), hovertemplate="%{x}<br>Profit %{customdata}<extra></extra>")
        fig.add_bar(x=labels, y=view["Loss"], name="Loss", marker_color="#d62728",
                    customdata=view["Loss"].map(inr), hovertemplate="%{x}<br>Loss %{customdata}<extra></extra>")
        fig.add_scatter(x=labels, y=view["Net P&L"], name="Net P&L", mode="lines+markers",
                        line=dict(color="#1f3b73"), customdata=view["Net P&L"].map(inr),
                        hovertemplate="%{x}<br>Net %{customdata}<extra></extra>")
        fig.update_layout(barmode="relative", height=440, margin=dict(l=10, r=10, t=30, b=10),
                          legend=dict(orientation="h", y=1.08), yaxis_title="₹", xaxis_tickangle=-45)
        st.plotly_chart(fig, use_container_width=True)

        cols = ["Month", "FY", "Lots", "Stocks", "Invested", "Sale Value", "Profit", "Loss", "Net P&L", "Return %",
                "STCG P&L", "LTCG P&L"]
        table(view, cols, "Month", True, "monthly_pnl.csv",
              sums=["Lots", "Invested", "Sale Value", "Profit", "Loss", "Net P&L", "STCG P&L", "LTCG P&L"],
              unit="months", label_col="Month")
        st.markdown("**By financial year**")
        show(yearly_realised(monthly))
        st.caption("Profit and loss are summed per lot, so a month can show both. STCG = held ≤ 12 months, "
                   "LTCG = held > 12 months. Figures are before charges and tax.")

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
        sold_sel = sel[sel["Status"] == "Sold"]
        fig.add_scatter(x=sold_sel["Sell Date"], y=sold_sel["Sell Price"], mode="markers", name="Actual sell",
                        marker=dict(color="#d62728", size=10, symbol="triangle-down"))
        if "Best Sell Date" in sel:
            fig.add_scatter(x=sel["Best Sell Date"], y=sel["Best Sell Price"], mode="markers", name="Best sell",
                            marker=dict(color="#ff7f0e", size=12, symbol="star"))
        fig.update_layout(height=480, margin=dict(l=10, r=10, t=30, b=10), legend=dict(orientation="h"))
        st.plotly_chart(fig, use_container_width=True)
        st.caption("Chart and marker prices are adjusted for splits/bonuses.")
