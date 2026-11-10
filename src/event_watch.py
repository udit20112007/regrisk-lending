"""
THE RBI WATCH - finding new events automatically
================================================

RBI publishes every press release and every new rule in two public feeds
(RSS). This file reads those feeds and decides, for each item:

    "Is this something that could move fintech share prices?"

If yes, it is turned into a new row for data/events.csv.

How the decision is made (simple, readable rules - no AI):
  1. Throw away routine items (bond auctions, penalties on small banks...).
  2. ENTITY EVENT: the title names a company we track AND contains an action
     word such as "action against" or "lifts".
  3. SECTOR EVENT: the title is about a topic that matters to our business
     models, such as "digital lending" or "payment aggregator".
  4. Decide the direction from the wording:
        "lifts", "relaxes"...        -> easing
        "action against", "bars"...  -> tightening
        neither                      -> unclear   (a person should decide)

Events marked "unclear" are shown on the website but are left out of the
tightening / easing statistics until someone sets their direction.

The rules will sometimes be wrong. Every row they add is marked
added_by = auto, so it is easy to find and check.
"""

import re
import xml.etree.ElementTree as ET
import zlib
from datetime import datetime
from urllib.parse import parse_qs, urlparse

FEEDS = {
    "press": "https://rbi.org.in/pressreleases_rss.xml",
    "notification": "https://rbi.org.in/notifications_rss.xml",
}

# The stock market closes at 15:30 India time. News after that can only move
# prices on the next trading day.
MARKET_CLOSE = (15, 30)

# --- Step 1: routine items we never want -----------------------------------
SKIP = [
    r"monetary penalt", r"\bpenalt(y|ies) on\b", r"co-?operative", r"sahakari",
    r"certificate of (registration|authorisation)", r"\bauction", r"treasury bill",
    r"money market", r"government securit", r"state government", r"sanctions list", r"\buapa\b",
    r"foreign exchange", r"\bsurvey\b", r"\bbulletin\b", r"\bspeech\b", r"\bminutes\b",
    r"working paper", r"extension of period", r"\bresults? of\b",
]

# --- Step 3: topics that matter, and the business models they concern -------
# Specific topics count on their own.
TOPICS = {
    r"digital lending": ["lending_distribution", "lending_nbfc"],
    r"default loss guarantee": ["lending_distribution", "lending_nbfc"],
    r"lending service provider": ["lending_distribution"],
    r"co-?lending": ["lending_distribution", "lending_nbfc"],
    r"consumer credit": ["lending_nbfc", "cards", "lending_distribution"],
    r"unsecured (loan|lending|credit)": ["lending_nbfc", "lending_distribution"],
    r"risk weights?": ["lending_nbfc"],
    r"gold loans?": ["lending_nbfc"],
    r"microfinance": ["lending_nbfc"],
    r"payment aggregators?": ["payments"],
    r"prepaid payment instruments?": ["payments"],
    r"payments banks?": ["payments"],
    r"credit cards?": ["cards"],
    r"digital banking": ["bank_digital"],
}
# Broad topics only count when the title also contains an action word.
BROAD_TOPICS = {
    r"\bnbfcs?\b": ["lending_nbfc"],
    r"non-?banking financial": ["lending_nbfc"],
    r"payment system operators?": ["payments"],
    r"\bfintechs?\b": ["lending_distribution", "payments"],
}

# --- Step 4: direction words ------------------------------------------------
EASING = [
    r"\blifts?\b", r"\blifting\b", r"\bremoves?\b", r"\bremoval of\b", r"\bwithdraw", r"\brelax",
    r"\beas(es|ed|ing)\b", r"\brestor", r"\broll(s|ed)? back\b",
]
TIGHTENING = [
    r"action against", r"supervisory action", r"business restrictions?", r"imposes? restrictions?",
    r"cease and desist", r"\bbars?\b", r"\bbarred\b", r"\bprohibit", r"\bcurbs?\b",
    r"\bsupersed", r"\bsupersession\b", r"\bdirects?\b.*\b(stop|cease)\b",
]


def _matches(patterns, text: str) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


# ---------------------------------------------------------------------------
# READING A FEED
# ---------------------------------------------------------------------------
def parse_feed(xml_text: str, source: str) -> list:
    """
    Turn the feed's XML into a simple list of items:
        {"title", "link", "published" (a datetime), "source"}
    Items with a date we cannot read are skipped.
    """
    items = []
    root = ET.fromstring(xml_text)
    for node in root.iter("item"):
        title = " ".join((node.findtext("title") or "").split())      # tidy the spacing
        link = (node.findtext("link") or "").strip()
        raw_date = (node.findtext("pubDate") or "").strip()
        try:
            # RBI writes dates like "Mon, 09 Nov 2026 18:55:00" (India time)
            published = datetime.strptime(raw_date[:25].strip(), "%a, %d %b %Y %H:%M:%S")
        except ValueError:
            continue
        if title and link:
            items.append({"title": title, "link": link, "published": published, "source": source})
    return items


def event_id_from_link(link: str, source: str) -> str:
    """
    A short, stable name for an item, taken from the number in its web address:
    press release 63952 -> "R63952", notification 13751 -> "N13751".
    """
    query = {k.lower(): v for k, v in parse_qs(urlparse(link).query).items()}
    number = (query.get("prid") or query.get("id") or [""])[0]
    prefix = "R" if source == "press" else "N"
    if number.isdigit():
        return prefix + number
    return prefix + str(zlib.crc32(link.encode("utf-8")))     # fallback if the address has no number


# ---------------------------------------------------------------------------
# THE DECISION
# ---------------------------------------------------------------------------
def find_companies(title: str, tickers) -> list:
    """Which tracked companies does the title name? `tickers` is the table from data/tickers.csv."""
    found = []
    for _, row in tickers.iterrows():
        names = [n.strip() for n in str(row.get("aliases", "")).split("|") if n.strip()]
        if any(re.search(r"\b" + re.escape(name) + r"\b", title, flags=re.IGNORECASE) for name in names):
            found.append(row["ticker"])
    return found


def direction_of(title: str) -> str:
    """Easing words win, because 'lifts restrictions' also contains 'restrictions'."""
    if _matches(EASING, title):
        return "easing"
    if _matches(TIGHTENING, title):
        return "tightening"
    return "unclear"


def classify(item: dict, tickers) -> dict | None:
    """
    Decide if a feed item is an event for this project.
    Returns a row for data/events.csv, or None if the item is not relevant.
    """
    title = item["title"]
    if _matches(SKIP, title):
        return None

    direction = direction_of(title)
    has_action = direction != "unclear"
    companies = find_companies(title, tickers)

    models = []
    for pattern, topic_models in TOPICS.items():
        if re.search(pattern, title, flags=re.IGNORECASE):
            models += topic_models
    if has_action:
        for pattern, topic_models in BROAD_TOPICS.items():
            if re.search(pattern, title, flags=re.IGNORECASE):
                models += topic_models

    is_entity_event = bool(companies) and has_action
    is_sector_event = bool(models)
    if not (is_entity_event or is_sector_event):
        return None

    if is_entity_event:
        # the named companies' own business models are affected too
        for _, row in tickers.iterrows():
            if row["ticker"] in companies:
                models += row["models"] if isinstance(row["models"], list) else str(row["models"]).split(";")
    else:
        companies = []            # a company named in a general rule is not a target

    published = item["published"]
    after_hours = (published.hour, published.minute) >= MARKET_CLOSE
    return {
        "event_id": event_id_from_link(item["link"], item["source"]),
        "announce_date": published.strftime("%Y-%m-%d"),
        "after_hours": 1 if after_hours else 0,
        "direction": direction,
        "title": title,
        "target_tickers": ";".join(companies),
        "affected_models": ";".join(dict.fromkeys(models)),      # keep order, drop repeats
        "date_check": "verified",                                # the date comes from RBI itself
        "source_url": item["link"],
        "added_by": "auto",
    }
