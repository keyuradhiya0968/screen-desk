# Screen Desk

Daily stock screens built from BSE corporate filings. Every point a stock scores links to the filing behind it.

- Runs on GitHub's servers at 07:30 IST (Mon–Sat) and 18:00 IST (Mon–Fri). Nothing to install.
- Dashboard: `https://<your-username>.github.io/screen-desk/`
- Alerts: Telegram message when a stock at or above a screen's threshold files something new.

## First screen: Narrative / operator

Built from the Aerpace Industries case. Over the last 365 days of filings, a stock gets points for:

| Flag | Points |
|---|---|
| Name change | 2 |
| Open offer / change in control | 2 |
| Preferential issue / warrants | 2 |
| Exchange price/volume clarification | 2 |
| Rights issue, order/LOI/MoU, merger, split/bonus, fund-raise approval | 1 each |
| Renamed and current name has a buzzword (drone, aero, AI, green, EV…) | +1 |

Threshold: 5 points.

## Files

- `screener/bse.py` reads BSE's announcement feed, one day at a time
- `screener/screens.py` holds the flags and screens (add new screens here)
- `screener/run.py` runs daily: fetch, score, publish, alert
- `docs/index.html` is the dashboard; `docs/data.json` holds the latest results
- `data/` holds the flagged filings history (only filings that hit a flag are kept)

## History build-up

The first run reads the last few days, then backfills about 45 days per run. The full 365 days take about 8 runs (around 4 days). Until then, scores only count the history collected so far; the dashboard shows the coverage.
