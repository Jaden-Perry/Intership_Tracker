# Internship Tracker

Checks bulge bracket, elite boutique/middle market, PE, asset management, and
wealth management career pages hourly (47 firms) for new sophomore- and
junior-eligible internship
postings, emails an alert when something new shows up, and publishes a
dashboard via GitHub Pages. Also sends a twice-daily "markets brief" email —
an interview-prep-focused rundown of what's moving in markets and why, built
for answering the classic "walk me through the markets" interview question.

## How it works

- `scripts/check_postings.py` runs on a schedule (GitHub Actions, hourly).
- For each firm in `config/firms.json`, it loads the careers page in headless
  Chromium (via Playwright) and pulls out links whose text looks like an
  internship/program posting.
- Each candidate is classified as **open_now** (sophomore-eligible),
  **not_yet_eligible** (junior-year Summer Analyst), or **unknown**, using
  keyword rules in `scripts/classify.py`.
- Results are diffed against `data/state.json` (committed to the repo, so
  state persists between runs). Anything new triggers an email via Resend
  and gets added to `docs/dashboard.json`, which `docs/index.html` renders.
- `config/tracked_programs.json` is a manually curated list of programs we
  know these firms run but that aren't posted yet — shown in the "Opens
  soon" section until the real posting is detected.

### Markets brief

- `scripts/market_brief.py` runs on a schedule (GitHub Actions,
  `.github/workflows/market_brief.yml`), weekdays only, ~7am ET (before the
  open) and ~5pm ET (after the close). Run manually any time from the
  Actions tab ("Markets brief" → Run workflow) to test.
- `scripts/market_data.py` pulls index/yield/commodity levels (S&P 500, Dow,
  Nasdaq, VIX, 10-year Treasury yield, crude, gold, dollar index) from
  Yahoo Finance's public chart endpoint — free, no API key.
- `scripts/market_news.py` pulls headlines from a handful of public RSS
  feeds (CNBC, MarketWatch, WSJ Markets, Yahoo Finance) — also free, no key.
- `scripts/brief_writer.py` sends that data to Claude (Anthropic API), which
  writes the actual brief: an interview-ready talking point, an interpreted
  (not just restated) market snapshot, a handful of stories tied to sectors
  and deal activity relevant to the firms in `config/firms.json`, and a
  "jargon of the day" explainer. This LLM step is what makes it a genuine
  explainer instead of a reformatted headline list — it costs roughly a
  couple cents per email (a few cents a day across both runs).
- Add/edit tracked tickers or RSS feeds in `config/market_brief.json`.

## One-time setup

1. **Push this repo to GitHub** (public, so Actions minutes and Pages are free).
2. **Add repo secrets** (Settings → Secrets and variables → Actions):
   - `RESEND_API_KEY` — from resend.com
   - `ALERT_EMAIL` — the address to send alerts to (used for both internship
     alerts and the markets brief)
   - `ALERT_FROM_EMAIL` — optional, defaults to `onboarding@resend.dev`
   - `ANTHROPIC_API_KEY` — from console.anthropic.com, only needed for the
     markets brief
3. **Enable GitHub Pages**: Settings → Pages → Source = "GitHub Actions".
4. Push a commit (or run either workflow manually from the Actions tab) to
   trigger the first run.

## Running locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python scripts/check_postings.py
```

Open `docs/index.html` in a browser (or `python3 -m http.server -d docs`) to
view the dashboard against local data.

## Adjusting what's tracked

- Add/edit firms in `config/firms.json`.
- Add/edit "opens soon" seed programs in `config/tracked_programs.json`.
- Tune keyword matching in `scripts/classify.py` if a firm's postings are
  landing in the wrong bucket, or not being picked up at all.
- Check the "Firm check status" row on the dashboard — firms flagged
  `error` or `low_confidence` mean the scraper couldn't reliably read that
  page and the config may need adjusting (e.g. a changed URL, or a page
  that needs a different extraction approach).
