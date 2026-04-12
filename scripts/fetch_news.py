#!/usr/bin/env python3
"""
Yakuza fan site news aggregator.
Polls RSS feeds from gaming sites, filters for RGG/Yakuza content,
and generates Hugo markdown files in content/news/.
Deduplication is handled via scripts/seen_articles.json.
"""

import feedparser
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────

FEEDS = [
    # Specialist / JP-focused — highest hit rate for RGG news
    {"name": "Gematsu",        "url": "https://gematsu.com/feed/"},
    {"name": "Siliconera",     "url": "https://www.siliconera.com/feed/"},
    {"name": "RPGSite",        "url": "https://www.rpgsite.net/feed.xml"},
    # Broad gaming press — good volume, lower hit rate
    {"name": "Push Square",    "url": "https://www.pushsquare.com/feeds/latest"},
    {"name": "Eurogamer",      "url": "https://www.eurogamer.net/?format=rss"},
    {"name": "The Gamer",      "url": "https://www.thegamer.com/feed/"},
    {"name": "Destructoid",    "url": "https://www.destructoid.com/feed/"},
    {"name": "VGC",            "url": "https://www.videogameschronicle.com/feed/"},
    {"name": "IGN",            "url": "https://feeds.feedburner.com/ign/games-all"},
    {"name": "Kotaku",         "url": "https://kotaku.com/rss"},
    {"name": "PC Gamer",       "url": "https://www.pcgamer.com/rss/"},
]

# Spoof a real browser User-Agent — some feeds block default Python/feedparser UA
USER_AGENT = (
    "Mozilla/5.0 (compatible; RGGArchiveBot/1.0; "
    "+https://tetsuakira-vk.github.io/yakuzafansite/)"
)

# Discord webhook URL — set as DISCORD_WEBHOOK secret in GitHub repo settings.
# If not set, alerting is silently skipped.
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK", "")

# Case-insensitive. Matched against article title + description combined.
KEYWORDS = [
    "yakuza",
    "like a dragon",
    "ryu ga gotoku",
    "rgg studio",
    "rgg",
    "infinite wealth",
    "pirate yakuza",
    "like a dragon: ishin",
    "like a dragon gaiden",
    "lost judgment",
    "judgment",  # broad, but Yakuza coverage sites rarely use this word otherwise
]

# Repo root is one level up from this script
REPO_ROOT    = Path(__file__).parent.parent
NEWS_DIR     = REPO_ROOT / "content" / "news"
SEEN_FILE    = Path(__file__).parent / "seen_articles.json"

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_seen() -> set:
    if SEEN_FILE.exists():
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(seen), f, indent=2)


def matches_keywords(text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in KEYWORDS)


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80]


def excerpt(text: str, max_chars: int = 300) -> str:
    """Strip HTML tags and trim to a clean excerpt."""
    clean = re.sub(r"<[^>]+>", "", text or "")
    clean = re.sub(r"\s+", " ", clean).strip()
    if len(clean) > max_chars:
        clean = clean[:max_chars].rsplit(" ", 1)[0] + "…"
    return clean


def parse_date(entry) -> datetime:
    """Return a timezone-aware datetime from a feedparser entry."""
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def escape_yaml(text: str) -> str:
    """Wrap in double-quotes and escape internal double-quotes for YAML."""
    return '"' + text.replace('"', '\\"') + '"'


def write_post(entry, source_name: str) -> Path:
    title    = entry.get("title", "Untitled").strip()
    link     = entry.get("link", "").strip()
    summary  = excerpt(entry.get("summary", entry.get("description", "")))
    pub_date = parse_date(entry)

    date_str = pub_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    date_prefix = pub_date.strftime("%Y-%m-%d")
    slug = f"{date_prefix}-{slugify(title)}"
    filepath = NEWS_DIR / f"{slug}.md"

    # Don't overwrite if somehow already present
    if filepath.exists():
        return filepath

    tags = derive_tags(title + " " + summary)

    content = f"""---
title: {escape_yaml(title)}
date: {date_str}
draft: false
categories: ["News"]
tags: {json.dumps(tags)}
source: {escape_yaml(source_name)}
source_url: {escape_yaml(link)}
summary: {escape_yaml(summary)}
---

{summary}

**Source:** [{source_name}]({link})
"""

    filepath.write_text(content, encoding="utf-8")
    return filepath


def derive_tags(text: str) -> list:
    """Generate a small set of relevant tags from the article text."""
    lower = text.lower()
    tags  = ["News"]
    mapping = {
        "yakuza 0":              "Yakuza 0",
        "kiwami 2":              "Yakuza Kiwami 2",
        "kiwami":                "Yakuza Kiwami",
        "yakuza 3":              "Yakuza 3",
        "yakuza 4":              "Yakuza 4",
        "yakuza 5":              "Yakuza 5",
        "yakuza 6":              "Yakuza 6",
        "infinite wealth":       "Like a Dragon: Infinite Wealth",
        "pirate yakuza":         "Pirate Yakuza in Hawaii",
        "ishin":                 "Like a Dragon: Ishin",
        "gaiden":                "Like a Dragon Gaiden",
        "like a dragon":         "Like a Dragon",
        "lost judgment":         "Lost Judgment",
        "judgment":              "Judgment",
        "ichiban":               "Ichiban Kasuga",
        "kiryu":                 "Kazuma Kiryu",
        "majima":                "Goro Majima",
        "rgg studio":            "RGG Studio",
        "ryu ga gotoku":         "Ryu Ga Gotoku",
        "pc":                    "PC",
        "ps5":                   "PS5",
        "xbox":                  "Xbox",
        "dlc":                   "DLC",
        "update":                "Update",
    }
    for keyword, tag in mapping.items():
        if keyword in lower and tag not in tags:
            tags.append(tag)
    return tags

# ── Discord alerting ──────────────────────────────────────────────────────────

def notify_discord(new_posts: list):
    """Post a summary to Discord when new articles are published."""
    if not DISCORD_WEBHOOK:
        return
    try:
        import json as _json
        count = len(new_posts)
        lines = "\n".join(f"• {p.replace('.md', '').split('-', 3)[-1].replace('-', ' ').title()}" for p in new_posts[:10])
        if count > 10:
            lines += f"\n…and {count - 10} more"
        payload = {
            "username": "RGG Archive News",
            "avatar_url": "https://cdn.akamai.steamstatic.com/steam/apps/638970/header.jpg",
            "embeds": [{
                "title": f"📰 {count} new Yakuza article{'s' if count != 1 else ''} posted",
                "description": lines,
                "url": "https://tetsuakira-vk.github.io/yakuzafansite/news/",
                "color": 0xC0392B,  # Yakuza red
            }]
        }
        data = _json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            DISCORD_WEBHOOK,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        print("Discord notification sent.")
    except Exception as e:
        print(f"Discord notification failed (non-fatal): {e}", file=sys.stderr)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    NEWS_DIR.mkdir(parents=True, exist_ok=True)
    seen = load_seen()
    new_posts = []

    for feed_cfg in FEEDS:
        name = feed_cfg["name"]
        url  = feed_cfg["url"]
        print(f"Fetching {name}…", flush=True)

        try:
            # Fetch raw bytes with a browser-like User-Agent, then hand to feedparser.
            # This avoids blocks from servers that reject the default Python UA.
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read()
            feed = feedparser.parse(raw)
        except Exception as e:
            print(f"  ERROR fetching {name}: {e}", file=sys.stderr)
            continue

        if feed.bozo and not feed.entries:
            print(f"  WARN: {name} feed may be malformed (bozo={feed.bozo_exception})")

        for entry in feed.entries:
            link = entry.get("link", "").strip()
            if not link:
                continue
            if link in seen:
                continue

            text = entry.get("title", "") + " " + entry.get("summary", entry.get("description", ""))
            if not matches_keywords(text):
                seen.add(link)  # mark seen so we don't re-check
                continue

            try:
                path = write_post(entry, name)
                new_posts.append(path.name)
                seen.add(link)
                print(f"  + {path.name}")
            except Exception as e:
                print(f"  ERROR writing post for '{entry.get('title')}': {e}", file=sys.stderr)
                seen.add(link)  # skip broken entries on retry too

    save_seen(seen)

    if new_posts:
        print(f"\n{len(new_posts)} new post(s) created.")
        notify_discord(new_posts)
    else:
        print("\nNo new matching articles.")

    # Exit code 0 always — the GitHub Action decides whether to commit
    # based on whether git detects changes, not this script's output.


if __name__ == "__main__":
    main()
