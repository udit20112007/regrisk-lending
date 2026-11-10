"""
CHECK RBI FOR NEW EVENTS
========================

Downloads RBI's two public feeds, picks out the items that matter for this
project (rules in src/event_watch.py) and adds any new ones to data/events.csv.

Run with:   python scripts/update_events.py

The GitHub workflow .github/workflows/watch-rbi.yml runs this every two hours
and saves the file back to the repository when something new is found.

To reject an event the watch added: do NOT delete its row (it would come back
on the next run). Change its direction to "ignore" instead.
"""

import csv
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import event_study as es          # noqa: E402
from src import event_watch as watch       # noqa: E402

EVENTS_FILE = ROOT / "data" / "events.csv"
COLUMNS = ["event_id", "announce_date", "after_hours", "direction", "title", "target_tickers",
           "affected_models", "date_check", "source_url", "added_by"]


def download(url: str) -> str | None:
    """Fetch one feed. Tries three times. Returns None if it cannot be reached."""
    request = urllib.request.Request(url, headers={
        # RBI's site turns away requests that do not look like a browser
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/126.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", errors="replace")
        except Exception as error:                      # network trouble, timeout, blocked...
            print(f"  attempt {attempt + 1} failed for {url}: {error}")
            time.sleep(5)
    return None


def read_events() -> list:
    """Read data/events.csv as a list of rows. Older files have no added_by column."""
    with open(EVENTS_FILE, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row.setdefault("added_by", "manual")
        if not row["added_by"]:
            row["added_by"] = "manual"
    return rows


def write_events(rows: list) -> None:
    with open(EVENTS_FILE, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    tickers = es.load_tickers()
    rows = read_events()
    known_ids = {row["event_id"] for row in rows}
    known_links = {row["source_url"] for row in rows}

    feeds_read = 0
    new_rows = []
    for source, url in watch.FEEDS.items():
        print(f"Reading RBI {source} feed...")
        xml_text = download(url)
        if xml_text is None:
            continue
        try:
            items = watch.parse_feed(xml_text, source)
        except Exception as error:
            print(f"  could not understand the feed: {error}")
            continue
        feeds_read += 1
        print(f"  {len(items)} items")
        for item in items:
            event = watch.classify(item, tickers)
            if event is None:
                continue
            if event["event_id"] in known_ids or event["source_url"] in known_links:
                continue
            known_ids.add(event["event_id"])
            known_links.add(event["source_url"])
            new_rows.append(event)

    if feeds_read == 0:
        # Fail loudly, so GitHub shows a red cross and emails you.
        raise SystemExit("Could not read either RBI feed. Nothing was changed.")

    for event in new_rows:
        print(f"  NEW  {event['announce_date']}  [{event['direction']}]  {event['title']}")
    if new_rows:
        rows.extend(new_rows)
        rows.sort(key=lambda row: row["announce_date"])
        write_events(rows)
    print(f"{len(new_rows)} new event(s) added." if new_rows else "No new events.")

    # Tell the GitHub workflow whether anything changed.
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        with open(output_file, "a", encoding="utf-8") as handle:
            handle.write(f"new_events={'true' if new_rows else 'false'}\n")


if __name__ == "__main__":
    main()
