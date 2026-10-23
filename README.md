# Stocks Post-Analysis

A Streamlit app that reads your Zerodha tradebooks and shows, in hindsight, the date each
stock lot could have been sold for the most profit, compared with what you actually made.

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

## How it works

1. **Tradebooks** (`postanalysis/tradebook.py`): finds the header row in each Console export and normalises the columns.
2. **Lots** (`postanalysis/lots.py`): matches sells to the oldest buys first (FIFO), per ISIN, across NSE and BSE.
3. **Prices** (`postanalysis/prices.py`): daily closes from Yahoo Finance (`SYMBOL.NS`, or `.BO` for BSE-only
   stocks), cached in `data/prices/`. For anything Yahoo lacks, drop a CSV named `<SYMBOL>.NS.csv` with
   columns `Date, Close, High, Stock Splits` into that folder.
4. **Analysis** (`postanalysis/analysis.py`): for each lot, the highest close between the day after
   purchase and the sell date (or today for held lots). Lot prices are rescaled for splits and bonuses.

## Limitations

- Figures are before brokerage, STT, stamp duty, DP charges and tax. The `Term` column marks STCG/LTCG.
- "Best" uses daily closes in hindsight. It is a review of timing, not a prediction.
- Dividends are not included.

## Tests

```bash
python -m pytest tests
```
