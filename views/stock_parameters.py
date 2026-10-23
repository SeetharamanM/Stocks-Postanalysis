"""PE, PEG, beta and alpha of each stock on the day it peaked while you held it."""

import pandas as pd
import plotly.express as px
import streamlit as st

from postanalysis.fundamentals import INDEX_TICKER, get_fundamentals, parameters_at
from postanalysis.prices import get_history
from postanalysis.ui import FUNDAMENTALS_CACHE, PRICE_CACHE, load_all, show, sidebar, tickers_for

st.title("Stock parameters at peak price")
st.caption("For every stock: the day it hit its highest close while you held it, and its valuation (PE, PEG) "
           "and risk-adjusted performance (beta, alpha vs NIFTY 50) on that day. Use it to spot the levels at "
           "which your stocks tended to top out.")

folder, uploads, as_of = sidebar()
trades, histories, analysed, _ = load_all(folder, uploads, as_of)
tickers = tickers_for(trades)


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def fundamentals(ticker: str, refresh_token: int) -> dict:
    try:
        return get_fundamentals(ticker, FUNDAMENTALS_CACHE, refresh=refresh_token > 0)
    except Exception as exc:
        return {"error": str(exc), "annual_eps": {}, "quarterly_eps": {}, "info": {}}


@st.cache_data(show_spinner="Fetching NIFTY 50 history…")
def index_history(start, end) -> pd.Series:
    try:
        return get_history(INDEX_TICKER, start, end, PRICE_CACHE)["Close"]
    except Exception:
        return pd.Series(dtype=float)


def peaks(lots: pd.DataFrame) -> pd.DataFrame:
    """One row per stock: the lot whose best close was highest, i.e. the stock's peak while held."""
    lots = lots.dropna(subset=["Best Sell Price"])
    idx = lots.groupby("ISIN")["Best Sell Price"].idxmax()
    out = lots.loc[idx, ["Symbol", "ISIN", "Status", "Best Sell Date", "Best Sell Price", "Best P&L", "Price Now"]]
    status = lots.groupby("ISIN")["Status"].agg(lambda s: "/".join(sorted(set(s))))
    out["Status"] = out["ISIN"].map(status)
    return out.rename(columns={"Best Sell Date": "Peak Date", "Best Sell Price": "Peak Price"})


with st.sidebar:
    st.header("Parameters")
    status = st.radio("Stocks", ["All", "Sold", "Held"], horizontal=True)
    lookback = st.selectbox("Alpha/beta window before the peak", ["6 months", "1 year", "2 years"], index=1)
    risk_free = st.number_input("Risk-free rate (% a year)", 0.0, 15.0, 6.5, 0.25,
                                help="Used for alpha. Roughly the 91-day T-bill / 10-year G-sec yield.") / 100
    refresh = st.button("Refresh fundamentals from Yahoo", help="Re-download EPS and ratios (cached for 7 days).")
lookback_days = {"6 months": 182, "1 year": 365, "2 years": 730}[lookback]
if refresh:
    st.session_state["refresh_token"] = st.session_state.get("refresh_token", 0) + 1
refresh_token = st.session_state.get("refresh_token", 0)

lots = analysed if status == "All" else analysed[analysed["Status"] == status]
peak_rows = peaks(lots).sort_values("Best P&L", ascending=False)
if peak_rows.empty:
    st.info("No stocks with price data for this selection.")
    st.stop()

symbols = peak_rows["Symbol"].tolist()
everything = st.checkbox(f"Analyse all {len(symbols)} stocks (first run downloads data for each — can take minutes)")
chosen = symbols if everything else st.multiselect(
    "Stocks", symbols, default=symbols[:15], help="Default: the 15 stocks with the largest profit at peak.")
peak_rows = peak_rows[peak_rows["Symbol"].isin(chosen)]
if peak_rows.empty:
    st.stop()

index_close = index_history(peak_rows["Peak Date"].min() - pd.Timedelta(days=lookback_days + 10), as_of)
if index_close.empty:
    st.warning("Could not load NIFTY 50 (^NSEI) prices, so beta and alpha are blank.")

rows, failed = [], []
progress = st.progress(0.0, "Loading fundamentals…")
for i, peak in enumerate(peak_rows.to_dict("records")):
    ticker = tickers[peak["ISIN"]]
    fund = fundamentals(ticker, refresh_token)
    if fund.get("error"):
        failed.append(peak["Symbol"])
    info = fund.get("info") or {}
    try:
        params = parameters_at(fund, histories[peak["ISIN"]], index_close, peak["Peak Date"], peak["Peak Price"],
                               lookback_days, risk_free)
    except Exception as exc:  # one stock's odd data shouldn't break the whole page
        params = {"EPS Basis": f"error: {exc}"}
        failed.append(peak["Symbol"])
    rows.append({
        **peak, **params,
        "PE Now": info.get("trailingPE"),
        "PEG Now": info.get("trailingPegRatio") or info.get("pegRatio"),
        "From Peak %": (peak["Price Now"] / peak["Peak Price"] - 1) * 100,
        "Sector": info.get("sector"),
        "Industry": info.get("industry"),
    })
    progress.progress((i + 1) / len(peak_rows), f"Loading fundamentals… {peak['Symbol']}")
progress.empty()
if failed:
    st.warning(f"Could not get fundamentals for: {', '.join(sorted(set(failed)))}. Their PE/PEG cells are blank.")

result = pd.DataFrame(rows)
for col in ["Traded Price", "EPS (TTM)", "PE", "EPS Growth %", "PEG", "Beta", "Alpha %", "Stock Return %",
            "Index Return %"]:
    result[col] = pd.to_numeric(result.get(col), errors="coerce")
for col in ["PE Now", "PEG Now"]:
    result[col] = pd.to_numeric(result[col], errors="coerce")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Median PE at peak", f"{result['PE'].median():.1f}" if result["PE"].notna().any() else "–",
          help="Half your stocks peaked above this PE")
m2.metric("Median PEG at peak", f"{result['PEG'].median():.2f}" if result["PEG"].notna().any() else "–",
          help="PEG above ~1.5–2 usually means the price ran ahead of earnings growth")
m3.metric("Positive alpha before peak", f"{(result['Alpha %'] > 0).mean():.0%}" if result["Alpha %"].notna().any()
          else "–", help="Share of stocks that beat NIFTY 50 after adjusting for beta")
m4.metric("Median beta", f"{result['Beta'].median():.2f}" if result["Beta"].notna().any() else "–")

cols = ["Symbol", "Status", "Peak Date", "Peak Price", "Traded Price", "Price Now", "From Peak %", "EPS (TTM)",
        "EPS Basis", "PE", "EPS Growth %", "PEG", "Beta", "Alpha %", "Stock Return %", "Index Return %",
        "PE Now", "PEG Now", "Best P&L", "Sector", "Industry"]
show(result[cols])
st.download_button("Download CSV", result[cols].to_csv(index=False), "stock_parameters_at_peak.csv", "text/csv")

chart = result.dropna(subset=["PE", "Alpha %"])
if not chart.empty:
    # Label only the most profitable stocks so a full-portfolio chart stays readable.
    chart = chart.assign(Label=chart["Symbol"].where(chart["Best P&L"].rank(ascending=False) <= 30, ""))
    fig = px.scatter(chart, x="PE", y="Alpha %", text="Label", color="Sector", size=chart["Best P&L"].clip(lower=1),
                     hover_name="Symbol", hover_data={"Peak Date": "|%d %b %Y", "PEG": ":.2f", "Beta": ":.2f",
                                                       "Sector": False, "Label": False},
                     title="PE vs alpha at each stock's peak (bubble size = profit at peak)")
    fig.update_traces(textposition="top center")
    fig.update_layout(height=520, margin=dict(l=10, r=10, t=50, b=10))
    st.plotly_chart(fig, use_container_width=True)

st.markdown(f"""
**How these are calculated**
- **Peak** – highest daily close between buying and selling (sold) or since buying (held), across all your lots.
- **PE** – price actually traded that day ÷ EPS of the last 4 reported quarters ended before the peak
  (falls back to the last annual EPS). Blank when EPS was negative.
- **PEG** – PE ÷ year-on-year EPS growth % at that time. Blank when growth was negative.
- **Beta / Alpha** – from daily returns vs NIFTY 50 over the {lookback} before the peak. Alpha is
  Jensen's alpha, annualised, using a {risk_free:.2%} risk-free rate: positive means the stock beat
  what its beta alone would predict.
- **PE Now / PEG Now** – Yahoo's current figures, for comparison.

Yahoo Finance only keeps about 4 years of annual and 5–6 quarters of quarterly results, so older peaks may
show annual EPS or none.
""")
