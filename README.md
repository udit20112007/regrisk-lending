# Regulatory risk and fintech lending partnerships

**How much is a fintech's loan-distribution partnership worth once RBI rule changes are allowed for?**

Fintechs such as Paytm earn fees by finding borrowers for banks and NBFCs. To win those
partnerships they often promise to cover the first slice of loan losses (a *default loss
guarantee*, capped by RBI at 5% of the loans disbursed). Two things decide whether such a
deal makes money: credit losses, and regulation. Most models only look at the first.

This project measures the second from share prices and feeds it into the deal model.

## How the three parts fit together

| Part | Question it answers | File |
|---|---|---|
| 1. Event study | When RBI acts, how much value do fintech shares lose, and how often does it happen? | `src/event_study.py` |
| 2. Lending model | For every Rs 100 lent, what do the fintech and the lender each earn? What guarantee level works best? | `src/lending_model.py` |
| 3. Combined model | What is the partnership worth after regulatory shocks? What do specific rule changes do to it? | `src/integration.py` |

The link: Part 1 produces **shocks per year** and **damage per shock** for a business model.
Part 3 treats each shock as a permanent cut to future loan volume of that size, and re-values
the partnership from Part 2. It also re-plays past shocks at random 3,000 times to show the
range of outcomes.

## Run it

```bash
pip install -r requirements.txt
python src/fetch_prices.py                  # downloads real share prices (needs internet)
python scripts/build_site.py                # runs the event study and builds the website
python -m http.server --directory site      # open the address it prints
python -m pytest -q                         # 24 checks on the calculations
```

**Important: sample data.** Until you run `fetch_prices.py`, the site uses
`data/sample_prices.csv`. Those prices are invented so the code can run offline. The site
shows a "Sample data" warning while they are in use. Never quote results from the sample data.

## How the website works

- **Python does the analysis.** `scripts/build_site.py` runs the event study and writes the
  results to `site/data.js`.
- **The page recalculates in the browser.** Moving a slider re-runs the lending model
  instantly. That needs the model in JavaScript, so `web/model.js` is a line-by-line copy of
  `src/lending_model.py` and `src/integration.py`.
- **A test keeps the two copies identical.** `tests/test_js_parity.py` runs both on three
  different deals and fails if any number differs. Python is the original.
- **No outside services.** Charts are hand-written SVG (`web/charts.js`) and the font is
  bundled, so the page loads instantly and works offline.

## Put it online with GitHub

The repository includes a GitHub Actions workflow (`.github/workflows/deploy.yml`). On every
push to `main`, and every Monday, it:

1. runs the tests (a failure stops the deployment)
2. downloads fresh share prices from Yahoo Finance
3. builds the website
4. publishes it on GitHub Pages

One-time setup: in the repository open **Settings → Pages → Build and deployment** and set
**Source** to **GitHub Actions**. Then push. The live address appears on the **Actions** tab
when the run finishes, in the form `https://YOUR-USERNAME.github.io/regrisk-lending/`.

If Yahoo Finance refuses the download, the workflow carries on with `data/prices.csv` from
the repository. Commit that file once from your own computer so there is always a fallback.
Without it the site uses the sample data and shows the warning.

## What is in the folder

```
src/event_study.py        Part 1
src/lending_model.py      Part 2
src/integration.py        Part 3
src/fetch_prices.py       downloads real prices from Yahoo Finance
src/make_sample_data.py   creates the made-up sample prices
data/events.csv           14 RBI actions, 2022 to 2026, each with a source link
data/tickers.csv          12 listed companies and their business models

web/index.html            the page
web/styles.css            its design (light and dark mode)
web/app.js                reads the sliders, runs the model, fills in the page
web/model.js              the JavaScript copy of the Python model
web/charts.js             the charts
web/fonts/                the Geist font (SIL Open Font License)

scripts/build_site.py     runs the event study and builds site/
.github/workflows/deploy.yml   tests, builds and publishes on GitHub Pages
tests/test_models.py      checks that the calculations are right
tests/test_js_parity.py   checks that JavaScript and Python give the same answers
STUDY_GUIDE.md            plain-language explanation of everything, plus interview questions
```

## Design

A light analytics dashboard with a dark mode. Chart colours are fixed by meaning: blue is the
fintech or the company in focus, orange is the lender or peer companies, grey is background
context. The colours were checked for contrast and for colour-blind readers in both modes.
To change the look, edit the variables at the top of `web/styles.css`.

## The RBI rules the model is built on

- **8 June 2023.** RBI allows default loss guarantees in digital lending, capped at 5% of the
  amount disbursed. The guarantee must be cash, a lien-marked fixed deposit or a bank
  guarantee, and must be invoked within 120 days of a missed payment.
  ([summary](https://corridalegal.com/revisiting-the-rbis-guidelines-on-default-loss-guarantee-in-digital-lending/))
- **May 2025.** NBFCs are told to ignore these guarantees when setting aside loss buffers.
  ([report](https://www.angelone.in/news/market-updates/rbi-reinstates-default-loss-guarantees-framework-for-nbfcs))
- **13 February 2026.** RBI lets NBFCs count the guarantee again, provided it is an integral
  part of the loan arrangement. Cover shrinks each time it is invoked.
  ([analysis](https://vinodkothari.com/2026/02/factoring-dlg-into-ecl-relief-but-not-a-free-pass/))

The model has a switch for the May 2025 rule and sliders for the cap, so each of these can
be tested.

## Before you rely on the results

1. **Check the event dates.** In `data/events.csv`, rows marked `check_day` have a verified
   month but the exact day is from memory. Confirm them against the linked source.
2. **Check the timing column.** `after_hours = 1` means the news came after the market
   closed, so the reaction is measured from the next trading day. This is confirmed for the
   Paytm Payments Bank order and the 2025 risk-weight rollback, and assumed for the rest.
   The `CAR(-1,+5)` window is included as a cross-check that is less sensitive to timing.
3. **Check the Yahoo symbols.** `fetch_prices.py` could not be run where this project was
   built (no access to Yahoo Finance). If a company fails to download, correct its
   `yahoo_symbol` in `data/tickers.csv`.
4. **The lending numbers are illustrative.** Fees, costs and default rates are reasonable
   starting values, not any company's actual figures. Replace them with numbers from annual
   reports and investor presentations where you can.

## Known limitations

- Only 14 events, and some sit close together (15 and 16 November 2023; 4 and 5 March 2024),
  so their windows overlap. Treat averages as indicative.
- The link from share-price damage to lost loan volume is an assumption. The app has a
  slider to test it.
- Defaults are spread evenly over the loan's life. Real loans default more in early months.
- The lender is assumed to stay in the deal whenever it earns its minimum return. The model
  has no term for "skin in the game", so it can understate how much lenders value a guarantee.

## Sources for the event list

Each row of `data/events.csv` carries its own link. Main sources: RBI circulars, Reuters,
Business Standard, Inc42 and Business Today.
