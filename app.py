"""Stocks Post-Analysis — Streamlit app for Zerodha equity tradebooks.

Privacy: the app never ships with trade data. Users upload their own
tradebook at runtime; it is processed in memory only and never written to
disk. Client ID, Trade ID and Order ID are dropped as soon as the file is read.
"""

from __future__ import annotations

import hmac
import io
from collections import deque

import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Stocks Post-Analysis", page_icon="📈", layout="wide")

# Columns that identify the account or broker order; never shown or kept.
SENSITIVE_COLUMNS = {"Client ID", "Trade ID", "Order ID"}
REQUIRED_COLUMNS = {"Symbol", "Trade Date", "Trade Type", "Quantity", "Price"}


# --------------------------------------------------------------------------- #
# Optional password gate (set APP_PASSWORD in Streamlit secrets to enable)
# --------------------------------------------------------------------------- #
def password_ok() -> bool:
    try:
        expected = st.secrets.get("APP_PASSWORD")
    except Exception:  # no secrets.toml at all
        expected = None
    if not expected:
        return True
    if st.session_state.get("auth_ok"):
        return True
    pwd = st.text_input("Password", type="password")
    if pwd:
        if hmac.compare_digest(pwd, str(expected)):
            st.session_state["auth_ok"] = True
            st.rerun()
        st.error("Incorrect password")
    return False


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #
def _find_header_row(raw: pd.DataFrame) -> int:
    for i, row in raw.iterrows():
        values = {str(v).strip() for v in row.values if pd.notna(v)}
        if {"Symbol", "Trade Type"} <= values:
            return int(i)
    raise ValueError("Could not find the 'Symbol' / 'Trade Type' header row.")


def _read_one(name: str, data: bytes) -> pd.DataFrame:
    buf = io.BytesIO(data)
    if name.lower().endswith(".csv"):
        raw = pd.read_csv(buf, header=None, dtype=str)
    else:
        raw = pd.read_excel(buf, header=None, dtype=str)
    hdr = _find_header_row(raw)
    df = raw.iloc[hdr + 1 :].copy()
    df.columns = [str(c).strip() if pd.notna(c) else f"_blank{i}" for i, c in enumerate(raw.iloc[hdr])]
    df = df.loc[:, [c for c in df.columns if not c.startswith("_blank")]]
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {', '.join(sorted(missing))}")
    keep_ids = df.get("Trade ID")  # used only for de-duplication, then dropped
    df = df.dropna(subset=["Symbol"])
    df["_dedupe"] = keep_ids.loc[df.index] if keep_ids is not None else None
    return df.drop(columns=[c for c in SENSITIVE_COLUMNS if c in df.columns])


@st.cache_data(show_spinner=False, max_entries=5)
def load_tradebooks(files: tuple[tuple[str, bytes], ...]) -> pd.DataFrame:
    frames = [_read_one(n, d) for n, d in files]
    df = pd.concat(frames, ignore_index=True)
    # Overlapping exports: drop duplicates by Trade ID when present.
    if df["_dedupe"].notna().any():
        df = df.drop_duplicates(subset=["_dedupe", "Symbol", "Trade Type"])
    df = df.drop(columns="_dedupe")

    df["Trade Type"] = df["Trade Type"].str.strip().str.lower()
    df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce")
    df["Price"] = pd.to_numeric(df["Price"], errors="coerce")
    df["Trade Date"] = pd.to_datetime(df["Trade Date"], errors="coerce")
    if "Order Execution Time" in df.columns:
        df["Exec Time"] = pd.to_datetime(df["Order Execution Time"], errors="coerce")
    else:
        df["Exec Time"] = df["Trade Date"]
    df["Exec Time"] = df["Exec Time"].fillna(df["Trade Date"])
    df = df.dropna(subset=["Quantity", "Price", "Trade Date"])
    df = df[df["Trade Type"].isin(["buy", "sell"])]
    df["Value"] = df["Quantity"] * df["Price"]
    df["Key"] = df["ISIN"] if "ISIN" in df.columns else df["Symbol"]
    return df.sort_values(["Exec Time", "Trade Type"]).reset_index(drop=True)


# --------------------------------------------------------------------------- #
# FIFO matching
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def fifo_match(df: pd.DataFrame):
    realized, open_lots, unmatched = [], [], []
    for key, g in df.groupby("Key", sort=False):
        symbol = g["Symbol"].iloc[-1]
        lots: deque[list] = deque()  # [qty, price, date]
        for side, qty, price, date in zip(g["Trade Type"], g["Quantity"], g["Price"], g["Trade Date"]):
            qty = float(qty)
            if side == "buy":
                lots.append([qty, float(price), date])
                continue
            sell_px = float(price)
            sell_dt = date
            while qty > 0 and lots:
                lot = lots[0]
                m = min(qty, lot[0])
                realized.append(
                    {
                        "Symbol": symbol,
                        "Buy Date": lot[2],
                        "Sell Date": sell_dt,
                        "Quantity": m,
                        "Buy Price": lot[1],
                        "Sell Price": sell_px,
                        "P&L": m * (sell_px - lot[1]),
                        "Holding Days": (sell_dt - lot[2]).days,
                    }
                )
                lot[0] -= m
                qty -= m
                if lot[0] <= 1e-9:
                    lots.popleft()
            if qty > 1e-9:  # sold shares bought before the tradebook window
                unmatched.append({"Symbol": symbol, "Sell Date": sell_dt, "Quantity": qty, "Sell Price": sell_px})
        if lots:
            q = sum(l[0] for l in lots)
            cost = sum(l[0] * l[1] for l in lots)
            open_lots.append(
                {
                    "Symbol": symbol,
                    "Quantity": q,
                    "Avg Cost": cost / q,
                    "Invested": cost,
                    "First Buy": min(l[2] for l in lots),
                }
            )
    rz = pd.DataFrame(realized)
    if not rz.empty:
        rz["Return %"] = (rz["Sell Price"] / rz["Buy Price"] - 1) * 100
        rz["Term"] = rz["Holding Days"].apply(lambda d: "Intraday" if d == 0 else ("Short (<1y)" if d < 365 else "Long (≥1y)"))
    return rz, pd.DataFrame(open_lots), pd.DataFrame(unmatched)


def inr(x: float) -> str:
    """Compact Indian-style amount for metric cards (₹57.2L, ₹1.3Cr)."""
    a = abs(x)
    if a >= 1e7:
        return f"₹{x / 1e7:.2f}Cr"
    if a >= 1e5:
        return f"₹{x / 1e5:.1f}L"
    return f"₹{x:,.0f}"


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
st.title("📈 Stocks Post-Analysis")

if not password_ok():
    st.stop()

with st.sidebar:
    st.header("Tradebook")
    uploads = st.file_uploader(
        "Upload Zerodha equity tradebook(s)",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
        help="Console → Reports → Tradebook → Equity → Download (XLSX or CSV).",
    )
    st.caption(
        "🔒 Files are processed in memory for this session only and are never "
        "stored. Client ID, Trade ID and Order ID are discarded on load."
    )

if not uploads:
    st.info("Upload your tradebook in the sidebar to begin.")
    st.stop()

try:
    trades = load_tradebooks(tuple((u.name, u.getvalue()) for u in uploads))
except Exception as e:  # show a friendly message, not a stack trace
    st.error(f"Could not read tradebook: {e}")
    st.stop()

# Filters
with st.sidebar:
    st.header("Filters")
    dmin, dmax = trades["Trade Date"].min().date(), trades["Trade Date"].max().date()
    dr = st.date_input("Date range", (dmin, dmax), min_value=dmin, max_value=dmax)
    symbols = st.multiselect("Symbols", sorted(trades["Symbol"].unique()))

# FIFO runs on the full history so costs are right; filters apply to results.
realized, open_pos, unmatched = fifo_match(trades)
start, end = (pd.Timestamp(dr[0]), pd.Timestamp(dr[1])) if isinstance(dr, tuple) and len(dr) == 2 else (pd.Timestamp(dmin), pd.Timestamp(dmax))

t = trades[(trades["Trade Date"] >= start) & (trades["Trade Date"] <= end)]
rz = realized[(realized["Sell Date"] >= start) & (realized["Sell Date"] <= end)] if not realized.empty else realized
if symbols:
    t = t[t["Symbol"].isin(symbols)]
    rz = rz[rz["Symbol"].isin(symbols)] if not rz.empty else rz
    open_pos = open_pos[open_pos["Symbol"].isin(symbols)] if not open_pos.empty else open_pos
    unmatched = unmatched[unmatched["Symbol"].isin(symbols)] if not unmatched.empty else unmatched

buys, sells = t[t["Trade Type"] == "buy"], t[t["Trade Type"] == "sell"]
total_pnl = rz["P&L"].sum() if not rz.empty else 0.0
by_symbol = rz.groupby("Symbol")["P&L"].sum() if not rz.empty else pd.Series(dtype=float)
win_rate = (by_symbol > 0).mean() * 100 if len(by_symbol) else 0.0

c = st.columns(6)
c[0].metric("Trades", f"{len(t):,}")
c[1].metric("Symbols traded", f"{t['Symbol'].nunique():,}")
c[2].metric("Bought", inr(buys["Value"].sum()))
c[3].metric("Sold", inr(sells["Value"].sum()))
c[4].metric("Realized P&L (gross)", inr(total_pnl))
c[5].metric("Winning symbols", f"{win_rate:.0f}%")
st.caption("P&L is FIFO-matched and gross — brokerage, STT and other charges are not deducted.")

if not unmatched.empty:
    st.warning(
        f"{len(unmatched)} sell(s) of {unmatched['Symbol'].nunique()} symbol(s) had no matching buy in the "
        "uploaded period (shares bought earlier). Upload older tradebooks too for complete P&L."
    )

tab_over, tab_real, tab_open, tab_trades = st.tabs(["Overview", "Realized P&L", "Open positions", "Trades"])

with tab_over:
    daily = t.groupby([t["Trade Date"].dt.to_period("M").dt.to_timestamp(), "Trade Type"])["Value"].sum().reset_index()
    daily.columns = ["Month", "Side", "Value"]
    st.plotly_chart(
        px.bar(daily, x="Month", y="Value", color="Side", barmode="group", title="Monthly turnover",
               color_discrete_map={"buy": "#2E86DE", "sell": "#E67E22"}),
        use_container_width=True,
    )
    if not rz.empty:
        cum = rz.sort_values("Sell Date").groupby("Sell Date")["P&L"].sum().cumsum().reset_index()
        st.plotly_chart(px.area(cum, x="Sell Date", y="P&L", title="Cumulative realized P&L"), use_container_width=True)

with tab_real:
    if rz.empty:
        st.info("No realized trades in the selected range.")
    else:
        l, r = st.columns(2)
        sym = by_symbol.sort_values()
        top = pd.concat([sym.head(10), sym.tail(10)]).drop_duplicates().reset_index()
        top["Result"] = top["P&L"].apply(lambda v: "Profit" if v >= 0 else "Loss")
        l.plotly_chart(
            px.bar(top, x="P&L", y="Symbol", orientation="h", color="Result", title="Top winners & losers",
                   color_discrete_map={"Profit": "#27AE60", "Loss": "#C0392B"}),
            use_container_width=True,
        )
        monthly = rz.groupby(rz["Sell Date"].dt.to_period("M").dt.to_timestamp())["P&L"].sum().reset_index()
        r.plotly_chart(px.bar(monthly, x="Sell Date", y="P&L", title="Realized P&L by month"), use_container_width=True)

        term = rz.groupby("Term").agg(Trades=("P&L", "size"), PnL=("P&L", "sum"), AvgDays=("Holding Days", "mean")).reset_index()
        st.subheader("By holding period")
        st.dataframe(term.style.format({"PnL": "₹{:,.0f}", "AvgDays": "{:.0f}"}), hide_index=True, use_container_width=True)

        st.subheader("Per symbol")
        summary = (
            rz.groupby("Symbol")
            .agg(Qty=("Quantity", "sum"), Invested=("Buy Price", lambda s: (s * rz.loc[s.index, "Quantity"]).sum()),
                 PnL=("P&L", "sum"), AvgDays=("Holding Days", "mean"))
            .assign(ReturnPct=lambda d: d["PnL"] / d["Invested"] * 100)
            .sort_values("PnL", ascending=False)
            .reset_index()
        )
        st.dataframe(
            summary.style.format({"Invested": "₹{:,.0f}", "PnL": "₹{:,.0f}", "AvgDays": "{:.0f}", "ReturnPct": "{:.1f}%"}),
            hide_index=True, use_container_width=True,
        )
        with st.expander("Matched lots"):
            st.dataframe(rz.sort_values("Sell Date", ascending=False), hide_index=True, use_container_width=True)

with tab_open:
    if open_pos.empty:
        st.info("No open positions.")
    else:
        op = open_pos.sort_values("Invested", ascending=False)
        st.metric("Capital in open positions", inr(op["Invested"].sum()))
        st.plotly_chart(px.treemap(op, path=["Symbol"], values="Invested", title="Allocation by cost"), use_container_width=True)
        st.dataframe(op.style.format({"Avg Cost": "₹{:,.2f}", "Invested": "₹{:,.0f}"}), hide_index=True, use_container_width=True)
        st.caption("Cost basis from the uploaded tradebook only; live prices are not fetched.")

with tab_trades:
    show = [c for c in ["Trade Date", "Symbol", "Exchange", "Series", "Trade Type", "Quantity", "Price", "Value"] if c in t.columns]
    st.dataframe(t[show].sort_values("Trade Date", ascending=False), hide_index=True, use_container_width=True)
