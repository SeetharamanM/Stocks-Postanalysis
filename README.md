# Stocks Post-Analysis

A Streamlit app for analysing a Zerodha **equity tradebook**: turnover, FIFO-matched realised P&L, holding-period breakdown, winners and losers, and open positions with their cost basis.

## Privacy

- The app has **no trade data built in**. Each user uploads their own tradebook (XLSX or CSV) in the sidebar.
- Uploaded files stay in memory for that session only and are never written to disk.
- **Client ID, Trade ID and Order ID are dropped as soon as the file is read**, so they never appear in the UI.
- `.gitignore` blocks `*.xlsx` / `*.csv` and `.streamlit/secrets.toml`, so new data or secrets don't get committed by accident.
- You can add an optional password: set `APP_PASSWORD` in the app's secrets.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Push this repository to GitHub. A private repository works.
2. Go to <https://share.streamlit.io>, click **Create app**, and pick this repository, its branch, and `app.py` as the main file.
3. Optional but recommended: under **Advanced settings → Secrets**, add:
   ```toml
   APP_PASSWORD = "choose-a-strong-password"
   ```
4. Click **Deploy**.

## Notes

- P&L is **gross**. Brokerage, STT, GST and stamp duty are not deducted.
- Selling shares that were bought before the uploaded period leaves the sale unmatched, and the app warns you when this happens. To get complete P&L, upload older tradebooks too. You can upload several files at once, and overlapping trades are de-duplicated.
- Live prices are not fetched. Open positions are shown at cost.
