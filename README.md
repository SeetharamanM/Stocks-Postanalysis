# Stocks Post-Analysis

A Streamlit app that reads your Zerodha tradebooks and shows, in hindsight, the date each
stock lot could have been sold for the most profit, compared with what you actually made.

The app has two pages (switch in the sidebar):

**📈 Sell analysis**
- **Sold stocks: did I sell at the right time?** For every sold lot: the best date between buying
  and selling, realised vs best P&L, missed profit, and how the price moved after you sold.
- **Held stocks: how are my holdings doing?** For every open lot: unrealised P&L, the peak price
  since buying and how far below it the stock is now, and when each lot turns long-term (LTCG).
- **Monthly P&L:** realised profit, loss and net P&L for every month of sale, with STCG/LTCG split,
  a chart, and totals per Indian financial year (April–March).

**📊 Stock parameters:** for each stock, the day it peaked while you held it, and on that day its
PE, PEG, EPS growth, beta and alpha vs NIFTY 50, alongside today's PE. EPS comes from Yahoo Finance
(about 4 years of annual and 5–6 quarters of quarterly results) and is cached in `data/fundamentals/`.

All amounts use Indian grouping (₹1,51,792; hover a figure for the lakh/crore form).

## Run it on your computer

```bash
pip install -r requirements.txt
streamlit run app.py
```

In the sidebar, set **Folder with all tradebook files** to the local folder that holds your
tradebook exports (e.g. `C:\Users\you\Documents\Tradebooks` or `~/Tradebooks`), or upload the files.

- Every `.xlsx` / `.csv` in the folder (and its subfolders) is loaded and merged.
- Overlapping exports are fine: duplicate trades are dropped by exchange + trade ID.
- Load **all years** of tradebooks. A sell without an earlier buy in the files is listed
  under "stocks sold with no matching buy" and left out of the analysis.

### Shares you never bought through Zerodha

Shares from an IPO allotment, a demerger (e.g. RAYMONDLSL, RAYMONDREL, ONESOURCE), a transfer-in
or a buy older than your oldest tradebook show up as "sold with no matching buy". Add them as
buy rows in a CSV in the tradebook folder, using the same columns as the tradebook:

```csv
Symbol,ISIN,Trade Date,Exchange,Trade Type,Quantity,Price,Trade ID
RAYMONDREL,INE1SY401010,2025-05-14,NSE,buy,19,0,MANUAL-1
```

Use the allotment / cost-of-acquisition price (for demergers, the cost split announced by the company)
and give each row a unique `Trade ID`. Splits and bonuses need no manual rows: they are applied
automatically from Yahoo's split data.

## How it works

1. **Tradebooks** (`postanalysis/tradebook.py`): finds the header row in each Console export and normalises the columns.
2. **Lots** (`postanalysis/lots.py`): restates trades for later splits/bonuses, then matches sells to the
   oldest buys first (FIFO), per ISIN, across NSE and BSE.
3. **Prices** (`postanalysis/prices.py`): daily closes from Yahoo Finance (`SYMBOL.NS`, or `.BO` for BSE-only
   stocks), cached in `data/prices/`. For anything Yahoo lacks, drop a CSV named `<SYMBOL>.NS.csv` with
   columns `Date, Close, High, Stock Splits` into that folder.
4. **Analysis** (`postanalysis/analysis.py`): for each lot, the highest close between the day after
   purchase and the sell date (or today for held lots).

5. **Fundamentals** (`postanalysis/fundamentals.py`): PE = traded price ÷ trailing-12-month EPS of the
   quarters reported before that date; PEG = PE ÷ year-on-year EPS growth; beta and Jensen's alpha from
   daily returns vs NIFTY 50 over a window before the peak.

Pages live in `views/`; `app.py` only sets up navigation, and `postanalysis/ui.py` holds what they share.

## Limitations

- Figures are before brokerage, STT, stamp duty, DP charges and tax. The `Term` column marks STCG/LTCG.
- "Best" uses daily closes in hindsight. It is a review of timing, not a prediction.
- Dividends are not included.

## Tests

```bash
python -m pytest tests
```
