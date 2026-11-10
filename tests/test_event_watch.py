"""
TESTS - does the automatic RBI watch pick the right items?

Each test feeds the rules a headline and checks the decision. The headlines
are modelled on real RBI press releases and notifications.

Run with:   python -m pytest -q
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import event_study as es          # noqa: E402
from src import event_watch as watch       # noqa: E402

TICKERS = es.load_tickers()

# A small copy of what RBI's feed looks like.
SAMPLE_FEED = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel><title>RBI Press Releases</title>
<item>
  <title><![CDATA[Auction of Government of India Dated Security]]></title>
  <description><![CDATA[<table><tr><td>Full text...</td></tr></table>]]></description>
  <link>https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=63952</link>
  <pubDate>Mon, 09 Nov 2026 18:55:00</pubDate>
</item>
<item>
  <title><![CDATA[Action against  Bajaj Finance Ltd. under Section 45L(1)(b)
     of the Reserve Bank of India Act, 1934]]></title>
  <description><![CDATA[<p>...</p>]]></description>
  <link>https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=56745</link>
  <pubDate>Wed, 15 Nov 2023 17:10:00</pubDate>
</item>
<item>
  <title><![CDATA[Item with a broken date]]></title>
  <link>https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=1</link>
  <pubDate>not a date</pubDate>
</item>
</channel></rss>"""


def item(title, when="Mon, 09 Nov 2026 18:55:00", source="press", number=70001):
    page = "BS_PressReleaseDisplay.aspx?prid" if source == "press" else "NotificationUser.aspx?Id"
    return {"title": title, "source": source,
            "link": f"https://www.rbi.org.in/scripts/{page}={number}",
            "published": datetime.strptime(when, "%a, %d %b %Y %H:%M:%S")}


# ---------------- reading the feed ----------------
def test_feed_is_read_and_bad_dates_are_skipped():
    items = watch.parse_feed(SAMPLE_FEED, "press")
    assert len(items) == 2                                   # the broken-date item is dropped
    assert items[0]["title"] == "Auction of Government of India Dated Security"
    assert items[0]["published"] == datetime(2026, 11, 9, 18, 55)
    # line breaks and double spaces inside a title are tidied up
    assert items[1]["title"].startswith("Action against Bajaj Finance Ltd. under Section 45L(1)(b) of")


def test_event_ids_come_from_the_web_address():
    assert watch.event_id_from_link("https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx?prid=63952", "press") == "R63952"
    assert watch.event_id_from_link("https://www.rbi.org.in/scripts/NotificationUser.aspx?Id=13751&Mode=0", "notification") == "N13751"


# ---------------- routine items are ignored ----------------
@pytest.mark.parametrize("title", [
    "Auction of Government of India Dated Security",
    "Money Market Operations as on November 08, 2026",
    "State Government Securities - Full Auction Result",
    "Reserve Bank cancels Certificate of Registration of Gandhinagar Leasing and Finance Ltd.",
    "Supersession of Board of Directors of Abhyudaya Co-operative Bank Ltd., Mumbai - Extension of period",
    "RBI imposes monetary penalty on Bajaj Finance Limited",
    "Foreign Exchange Management (Export and Import of Goods and Services) (Second Amendment) Regulations, 2026",
    "Implementation of Section 51A of UAPA, 1967: Updates to UNSC's 1988 (2011) Taliban Sanctions List",
    "Governor's Statement",
    "Kotak Mahindra Bank Limited - Annual Report released",          # a tracked company, but no action
])
def test_routine_items_are_ignored(title):
    assert watch.classify(item(title), TICKERS) is None


# ---------------- actions against a tracked company ----------------
def test_action_against_a_tracked_company_is_a_tightening_event():
    event = watch.classify(item("Action against Paytm Payments Bank Ltd under Section 35A of the Banking "
                                "Regulation Act, 1949", "Wed, 31 Jan 2024 17:30:00"), TICKERS)
    assert event["direction"] == "tightening"
    assert event["target_tickers"] == "PAYTM"
    assert "payments" in event["affected_models"].split(";")
    assert event["announce_date"] == "2024-01-31"
    assert event["after_hours"] == 1                           # 17:30 is after the 15:30 close
    assert event["added_by"] == "auto"
    assert event["event_id"] == "R70001"


def test_lifting_restrictions_is_an_easing_event():
    # "lifts" wins even though the title also says "restrictions"
    event = watch.classify(item("RBI lifts restrictions imposed on Bajaj Finance Limited"), TICKERS)
    assert event["direction"] == "easing"
    assert event["target_tickers"] == "BAJFINANCE"
    assert event["affected_models"] == "lending_nbfc"


def test_news_during_market_hours_is_not_after_hours():
    event = watch.classify(item("Supervisory Action against Kotak Mahindra Bank Limited under Section 35A",
                                "Wed, 24 Apr 2024 11:05:00"), TICKERS)
    assert event["after_hours"] == 0
    assert event["target_tickers"] == "KOTAKBANK"


# ---------------- sector-wide rules ----------------
def test_action_against_untracked_nbfcs_is_a_sector_event():
    event = watch.classify(item("RBI takes Supervisory action against four NBFCs"), TICKERS)
    assert event["direction"] == "tightening"
    assert event["target_tickers"] == ""                       # nobody we track was named
    assert event["affected_models"] == "lending_nbfc"


def test_new_rule_on_a_core_topic_is_kept_but_direction_is_left_open():
    event = watch.classify(item("Reserve Bank of India (Digital Lending) Directions, 2025",
                                "Thu, 08 May 2025 18:20:00", source="notification", number=12848), TICKERS)
    assert event["direction"] == "unclear"                     # the words do not say which way it cuts
    assert event["affected_models"] == "lending_distribution;lending_nbfc"
    assert event["event_id"] == "N12848"


def test_broad_topics_need_an_action_word():
    # a routine NBFC circular is not an event...
    assert watch.classify(item("Master Direction - Non-Banking Financial Company - Returns", source="notification"), TICKERS) is None
    # ...but restrictions on NBFCs are
    assert watch.classify(item("RBI imposes business restrictions on two Non-Banking Financial Companies"), TICKERS) is not None


@pytest.mark.parametrize("title, models", [
    ("Guidelines on Default Loss Guarantee (DLG) in Digital Lending", "lending_distribution;lending_nbfc"),
    ("Regulation of Payment Aggregators - Draft Directions", "payments"),
    ("Master Direction - Credit Card and Debit Card - Issuance and Conduct Directions", "cards"),
    ("Exposures of Scheduled Commercial Banks to NBFCs - Review of Risk Weights", "lending_nbfc"),
])
def test_topics_map_to_the_right_business_models(title, models):
    event = watch.classify(item(title, source="notification"), TICKERS)
    assert event is not None
    assert event["affected_models"] == models


# ---------------- the event study copes with what the watch adds ----------------
def test_rejected_and_unclear_events_are_handled(tmp_path, monkeypatch):
    events_file = tmp_path / "events.csv"
    events_file.write_text(
        "event_id,announce_date,after_hours,direction,title,target_tickers,affected_models,date_check,source_url,added_by\n"
        "E1,2024-01-31,1,tightening,One,PAYTM,payments,verified,https://x/1,manual\n"
        "R2,2025-03-03,0,unclear,Two,,lending_nbfc,verified,https://x/2,auto\n"
        "R3,2025-04-04,0,ignore,Three,,payments,verified,https://x/3,auto\n")
    (tmp_path / "tickers.csv").write_text((es.DATA_DIR / "tickers.csv").read_text())
    monkeypatch.setattr(es, "DATA_DIR", tmp_path)
    events = es.load_events()
    assert list(events["event_id"]) == ["E1", "R2"]            # the "ignore" row is dropped
    assert list(events["added_by"]) == ["manual", "auto"]
