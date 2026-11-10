# Study guide

Read this before you put the project on your CV. An interviewer will ask you to explain it,
change an assumption, or defend a choice. This guide prepares you for that.

Suggested order: read section 1, open the site, then read sections 2 to 4 with the code open
beside you.

---

## 1. The project in 60 seconds

> "Fintechs like Paytm distribute loans for banks and NBFCs and often guarantee the first
> 5% of losses. I wanted to know how much regulatory risk takes off the value of such a
> partnership. First I ran an event study on 14 RBI actions to measure how often shocks hit
> each fintech business model and how much value they destroy. Then I built a model of the
> lending deal that shows what each side earns and which guarantee level works best. Finally
> I joined the two: each shock cuts future loan volume, so I can value the partnership with
> regulatory risk included and stress-test specific rule changes."

Learn this paragraph well enough to say it in your own words.

---

## 2. Part 1: the event study

### The idea

A share price moves every day, mostly because the whole market moved. To find the effect of
one piece of news, remove the market's share. What remains is the **abnormal return**.

### The five steps (all in `study_one` in `src/event_study.py`)

1. **Fit a line on a calm period.** Take 120 trading days ending 11 days before the event.
   Fit `stock return = alpha + beta × market return`. Beta is how strongly the stock follows
   the market. A beta of 1.3 means it usually moves 1.3% when the market moves 1%.
2. **Predict.** On each day around the event, the line says what the stock "should" have done.
3. **Subtract.** Abnormal return = actual return − predicted return.
4. **Add up.** The sum over several days is the **cumulative abnormal return (CAR)**. The main
   window is day 0 to day +5.
5. **Test.** Compare the CAR with the stock's normal day-to-day noise. This gives a t-statistic
   and a p-value. A p-value below 0.05 means a move this large would be unusual by chance.

### Details you should be able to explain

| Choice | Reason |
|---|---|
| Log returns | They can be added across days. Ordinary percentage returns cannot. |
| 10-day gap before the event | News sometimes leaks. The gap keeps leaks out of the line. |
| Day 0 is the *reaction* day | RBI often announces after the market closes, so the first reaction is the next trading day. |
| Three groups of companies | The company RBI acted against, others with the same business model, and unrelated ones. Unrelated companies should barely move. If they do, something else happened that day. |
| A price rise counts as zero damage | A tightening that the market shrugged off did no harm. It should not offset a real loss elsewhere. |

### From event study to a risk number (`risk_by_model`)

- **Shocks per year** = tightening events that concern a business model ÷ years of data
- **Damage per shock** = average value lost on those events
- **Expected yearly drag** = shocks per year × damage per shock

Example: 1 shock a year that costs 6% on average is a 6% yearly drag.

---

## 3. Part 2: the lending deal

### Who does what

- The **fintech** finds the borrower and collects repayments. It earns a sourcing fee and a
  servicing fee from the lender.
- The **lender** (bank or NBFC) provides the money. It earns interest and bears credit losses.
- The **guarantee**: the fintech deposits up to 5% of the loan amount with the lender. Losses
  are paid out of this deposit first. It is not refilled once used.

### Following Rs 100 (`cohort_economics` in `src/lending_model.py`)

1. Build the repayment schedule of a normal EMI loan (`loan_balances`).
2. Assume defaults are spread evenly over the loan's life.
3. When a loan defaults, the loss is the unpaid balance × the share never recovered.
4. 120 days later the guarantee is invoked. The deposit pays what it can. The lender bears
   the rest.
5. Add up each side's income and costs.

Two costs that are easy to miss:

- **Cost of locked-up capital (fintech).** The deposit earns fixed-deposit interest (about
  6.5%), but the fintech's investors expect about 18%. The gap is a real cost.
- **Cost of the loss buffer (lender).** The lender plans for losses twice as high as expected
  and holds capital against the part the guarantee does not cover. If RBI says the guarantee
  cannot be counted (the May 2025 rule), this buffer gets larger.

### The main chart: which guarantee level is best?

- A **bigger** guarantee protects the lender, so the lender can live with more defaults.
- A **bigger** guarantee exposes the fintech, so the fintech can live with fewer defaults.
- The deal needs both. The best guarantee is where the two lines cross.
- If that crossing point is above 5%, the RBI cap is holding the deal back. The model tells
  you by how many percentage points.

### Break-even (`_highest_default_rate_where`)

The code finds the highest default rate at which a side is still satisfied. It uses
**bisection**: try the middle of the range, keep the half that contains the answer, repeat.

### Value of the whole partnership (`partnership_npv`)

Each month a new batch of loans is disbursed. Each batch produces the same pattern of cash,
scaled by its size. Add all batches, then discount to today at the fintech's cost of capital.
That is the **net present value (NPV)**.

---

## 4. Part 3: joining them

### The link (the assumption to defend)

When a shock hits, the share price falls by X%. The model reads this as "the market expects
future business to be X% smaller", so **each shock cuts all future loan volume by X%**.
Loans already given are unaffected.

This is a simplification. A share price also reflects payments, insurance and other
businesses. That is why the site has a slider: "lending is hit this many times harder than
the share price".

### Three tools (`src/integration.py`)

1. **One risk-adjusted number.** If shocks arrive at random at a steady rate, expected volume
   in month *t* is `planned volume × exp(−shocks per year × damage × t/12)`. The business
   shrinks a little, on average, every month. Shocks per year × damage works like an extra
   discount rate, which is why the site calls it the **regulatory risk premium**.
2. **Simulation.** 3,000 possible futures. Each month there is a small chance of a shock. When
   one arrives, the code picks one past shock at random and applies its damage. This shows
   the range of outcomes, the 1-in-20 bad case, and the chance of losing money.
3. **Rule-change scenarios.** Four specific changes: guarantee ignored in loss buffers, cap
   cut to 2.5%, guarantees banned, lending frozen for six months. If a change pushes the
   lender below its minimum return, the lender cuts the fintech's fee until it is back at
   the minimum. That is how a rule aimed at lenders reaches the fintech.

### A result that will surprise people

With the starting assumptions, a lower cap can *raise* the fintech's profit. The reason: the
guarantee ties up the fintech's expensive capital, and a lower cap frees it. The price is
safety. The highest default rate the deal survives falls sharply. Be ready to say both halves,
and to add that the model ignores one thing: lenders may refuse to partner at all with a
fintech that has no money at risk.

---

## 4b. The website

The site is three layers. Be clear about which is which.

| Layer | What it does | Files |
|---|---|---|
| Analysis (Python) | Runs the event study and saves the results | `src/`, `scripts/build_site.py` |
| Model in the browser (JavaScript) | Re-runs the lending model when a slider moves | `web/model.js` |
| Display (HTML, CSS, JavaScript) | Layout, charts, light and dark mode | `web/index.html`, `web/styles.css`, `web/charts.js`, `web/app.js` |

**Why is the model written twice?** A website on GitHub Pages cannot run Python. To make the
sliders respond instantly, the lending model has to run in the visitor's browser, and browsers
run JavaScript. So `web/model.js` is a line-by-line copy of the Python model.

**How do you know the copy is right?** `tests/test_js_parity.py` runs the Python model and the
JavaScript model on three different deals and compares over a hundred numbers. If any differs, the
test fails and the site is not published. Python is the original. If you change the model,
change Python first, then make the same change in `model.js` until the test passes.

**What to say in an interview.** The finance and the Python are yours to explain in depth.
For the front end, an honest answer is: "The analysis is in Python. The page uses a tested
JavaScript copy of the same model so it can recalculate without a server."

---

## 5. Words you must know

| Term | Meaning |
|---|---|
| Default loss guarantee (DLG, formerly FLDG) | The fintech's promise to cover the first slice of loan losses |
| Lending service provider (LSP) | RBI's name for the fintech in this arrangement |
| Regulated entity (RE) | The bank or NBFC that lends |
| NBFC | Non-banking financial company: lends like a bank but cannot take ordinary deposits |
| Loss given default (LGD) | Share of a defaulted balance that is never recovered |
| Return on assets (ROA) | Yearly profit ÷ loans outstanding |
| Expected credit loss (ECL) | The loss buffer a lender sets aside in advance |
| Abnormal return / CAR | Share price move not explained by the market / its sum over days |
| NPV | Value today of future cash flows |
| Monte Carlo simulation | Running a model thousands of times with random inputs |

---

## 6. Questions an interviewer may ask

**Why an event study and not a survey of news?**
Share prices put a rupee value on news the same day, from people with money at stake.

**Why the Nifty 50 as the market?**
It is the standard broad benchmark. A fair extension is to test the Nifty Financial Services
index and see if results change.

**Fourteen events is a small sample. Can you trust the averages?**
Only as a guide. That is why the site reports p-values, shows individual events, and the
simulation re-plays actual past shocks without assuming a smooth distribution.

**Two of your events are one day apart. Is that a problem?**
Yes. Their six-day windows overlap, so each picks up the other. The cleaner options are to
merge them into one event or to use the two-day window.

**Does a share price fall really mean lost lending volume?**
Not exactly. It is the model's central assumption, and the pass-through slider tests it.

**Why does the fintech's cost of capital matter so much?**
Because the guarantee is cash locked away. At 18% cost of capital and 6.5% deposit interest,
every Rs 100 locked for a year costs about Rs 11.50.

**What would you add with more time?**
Front-loaded default timing, a "skin in the game" term for the lender, a sector index as the
benchmark, and real fee data from company filings.

---

## 7. Make it yours (do these before listing it on your CV)

1. Run `python src/fetch_prices.py` and look at the real results. Write down three findings.
2. Verify the five event dates marked `check_day` in `data/events.csv`.
3. Add two events of your own. Any RBI action from 2025 or 2026 that you find in the news.
4. Change one assumption in `DealInputs` using a number from a real annual report, and note
   where you found it.
5. Write a two-page memo with this outline:
   - The question, in two sentences
   - What the event study found (one chart, three numbers)
   - What the lending model found (the guarantee chart, the best level)
   - Value with and without regulatory risk
   - Your recommendation: what guarantee to offer, and which rule change to watch
   - Limitations
6. Put the code on GitHub with the README and a screenshot of the site using real data.

## 8. CV lines (fill the brackets from your real-data run)

- Built an event study of [14] RBI actions on [12] listed fintech and lending stocks in
  Python; estimated a regulatory risk premium of [X]% a year for loan-distribution models.
- Modelled the unit economics of fintech-lender partnerships under RBI's 5% default loss
  guarantee cap; identified the guarantee level that maximises the default rate the deal can
  absorb ([X]% against [Y]% at the cap).
- Combined both in a Monte Carlo valuation and an interactive web dashboard (GitHub Pages); showed that
  regulatory risk reduces partnership value by [X]% and that [scenario] is the most damaging
  rule change tested.
