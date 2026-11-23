# Screen Desk

Personal stock screens for Indian equities. Dashboard: `https://<username>.github.io/screen-desk/`

Four sections (tabs on the dashboard):

| Section | File | Screens |
|---|---|---|
| Technical | `screener/screens_technical.py` | Volume breakout · Near 52-week high · Delivery accumulation · Pullback in uptrend · Tight base · Relative strength leaders |
| Fundamental | `screener/screens_fundamental.py` | Quality compounder · Growth · Value · Penny (clean) · Turnaround · Dividend payers |
| Combined | `screener/screens_combined.py` | Recipes pairing one technical and one fundamental screen (Quality breakout, Growth near highs, Value being accumulated, and more); the dashboard also pairs any two by hand |
| Events | `screen_corporate_actions.py`, `screen_narrative.py`, `screen_bulk_deals.py` | Corporate actions with last day to buy · Narrative / operator pattern · Bulk & block deals |

Each screen's rules and thresholds sit at the top of its class.

## Alerts (Telegram, once set up)

- Combined recipes, when the technical signal is from the latest session (marked ⭐)
- Quality compounder reaching 9/10 for the first time
- Dividends yielding ≥ 3% with ≥ 2 trading days left to buy
- Narrative / operator pattern reaching 5 points

## Schedules

- **Daily screen run**: every 2 hours, 8 AM to 10 PM IST. NSE prices (kept for 260 trading days), 52-week highs, deals, RSS filings.
- **Fundamentals refresh**: nightly. Annual and quarterly statements from Yahoo Finance (yfinance) for NSE stocks trading ≥ ₹0.2 crore a day, each refreshed about weekly.
- **Apply update**: when a `.zip` is uploaded to the top of the repository; unpacks it, removes files in `DELETE.txt`, runs the screens.

## Data

NSE public files from nsearchives.nseindia.com (`sec_bhavdata_full`, `CM_52_wk_High_low`, `bulk.csv`, `block.csv`, RSS feeds, `EQUITY_L.csv`) and Yahoo Finance via yfinance. Yahoo data is unofficial: treat fundamental screens as shortlists and check the annual report.
