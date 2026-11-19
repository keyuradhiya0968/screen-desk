# Screen Desk

Personal stock screens for Indian equities, built only from public NSE files. Runs on GitHub every two hours (8 AM to 10 PM IST) and publishes a dashboard at `https://<username>.github.io/screen-desk/`.

## Screens

| Screen | File | What it finds |
|---|---|---|
| Volume breakout | `screener/screen_breakout.py` | Close above the 20-day high or a new 52-week high, volume ≥ 2× the 20-day average, delivery ≥ 50%, traded value ≥ ₹1 crore |
| Corporate actions | `screener/screen_corporate_actions.py` | Upcoming dividends, splits, bonus and rights with the last day to buy; alerts on dividends yielding ≥ 3% with ≥ 2 trading days left |
| Narrative / operator | `screener/screen_narrative.py` | Control changes, preferential issues/warrants, exchange volume queries, order headlines; alert at 5 points |
| Bulk & block deals | `screener/screen_bulk_deals.py` | Large disclosed trades over 10 sessions, netted per stock |

Each screen keeps its numbers in a `P = {...}` block (or constants) at the top of its file.

## Adding a screen

1. Create `screener/screen_<name>.py` with `ID`, `TITLE`, `DESCRIPTION`, `RULES` and `run(ctx)` returning hits.
2. Add it to `SCREENS` in `screener/run.py`.

## Data (all from nsearchives.nseindia.com)

- Daily prices and delivery: `sec_bhavdata_full_DDMMYYYY.csv` (65 trading days kept in `data/prices/`)
- 52-week highs: `CM_52_wk_High_low_DDMMYYYY.csv`
- Bulk and block deals: `bulk.csv`, `block.csv`
- Filings and corporate actions: NSE RSS feeds
- Stock list: `EQUITY_L.csv`, `SME_EQUITY_L.csv`

NSE sometimes refuses a whole run; the next run usually gets through, and the dashboard keeps the last good data.

## Updating the code

Upload `update.zip` to the top of the repository. The **Apply update** workflow unpacks it, removes files listed in its `DELETE.txt`, runs the screens and saves.
