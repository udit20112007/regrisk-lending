"""
BUILD THE WEBSITE
=================

The website in web/ is plain HTML, CSS and JavaScript, so GitHub Pages can
serve it directly. It needs one thing from Python: the event-study results.

This script
  1. runs the event study (src/event_study.py) on the share prices,
  2. saves every number the page needs to site/data.js,
  3. copies the page itself (web/) into site/.

Run with:   python scripts/build_site.py
Preview:    python -m http.server --directory site     (then open the address shown)

The GitHub workflow (.github/workflows/deploy.yml) runs this automatically.
"""

import json
import math
import shutil
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import event_study as es          # noqa: E402
from src import lending_model as lm        # noqa: E402

WEB = ROOT / "web"
SITE = ROOT / "site"

# The three reaction windows the page can show: 1, 2 or 6 trading days.
WINDOWS = {"1": "CAR(0,0)", "2": "CAR(0,+1)", "6": "CAR(0,+5)"}


def clean(value):
    """Make a value safe for JSON: no NaN, no NumPy types."""
    if value is None:
        return None
    if isinstance(value, (bool, str)):
        return value
    number = float(value)
    return None if math.isnan(number) else number


def collect_data() -> dict:
    """Run the event study and gather everything the page shows."""
    prices, is_sample = es.load_prices()
    events = es.load_events()
    tickers = es.load_tickers()
    results = es.run_event_study(prices, events, tickers)
    years = es.years_covered(prices)

    reaction_dates = results.groupby("event_id")["reaction_date"].first()

    event_rows = []
    for _, ev in events.iterrows():
        studied = ev["event_id"] in reaction_dates.index
        event_rows.append({
            "id": ev["event_id"],
            "date": ev["announce_date"].strftime("%Y-%m-%d"),
            "reaction_date": reaction_dates[ev["event_id"]].strftime("%Y-%m-%d") if studied else None,
            "title": ev["title"],
            "direction": ev["direction"],
            "date_check": ev["date_check"],
            "source_url": ev["source_url"],
            "studied": studied,
        })

    # one list of company reactions per event
    reactions = {}
    for event_id, group in results.groupby("event_id"):
        reactions[event_id] = [
            {
                "ticker": row["ticker"],
                "company": row["company"],
                "role": row["role"],
                "car": {key: clean(row[col]) for key, col in WINDOWS.items()},
                "p": {key: clean(row[col + " p"]) for key, col in WINDOWS.items()},
            }
            for _, row in group.iterrows()
        ]

    summary = {}
    for key, col in WINDOWS.items():
        table = es.summary_by_role(results, col)
        summary[key] = [{name: clean(value) for name, value in row.items()} for row in table.to_dict("records")]

    risk = es.risk_by_model(results, events, tickers, years)
    damages = {model: [clean(v) for v in es.damages_for_model(results, events, model)]
               for model in risk["model"]}

    return {
        "meta": {
            "built": date.today().isoformat(),
            "is_sample": is_sample,
            "years": clean(years),
            "price_start": prices.index[0].strftime("%Y-%m-%d"),
            "price_end": prices.index[-1].strftime("%Y-%m-%d"),
            "companies": int(len(tickers)),
        },
        "events": event_rows,
        "reactions": reactions,
        "summary": summary,
        "risk": [{name: clean(value) for name, value in row.items()} for row in risk.to_dict("records")],
        "damages": damages,
        "defaults": asdict(lm.DealInputs()),      # the starting slider values, straight from Python
    }


def main() -> None:
    data = collect_data()

    if SITE.exists():
        shutil.rmtree(SITE)
    shutil.copytree(WEB, SITE)

    # "</" is escaped so nothing in the data can end the script early.
    text = json.dumps(data, allow_nan=False).replace("</", "<\\/")
    (SITE / "data.js").write_text(f"window.REGRISK_DATA = {text};\n", encoding="utf-8")

    used = "SAMPLE prices (made up) - the page will show a warning" if data["meta"]["is_sample"] \
        else "REAL prices (data/prices.csv)"
    print(f"Built site/ with {len(data['events'])} events and {data['meta']['companies']} companies.")
    print(f"Data in the page: {used}")


if __name__ == "__main__":
    main()
