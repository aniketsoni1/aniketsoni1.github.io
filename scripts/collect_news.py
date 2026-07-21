"""
collect_news.py - ingestion + normalization layer for news signals.

Reads data/sources.yml, pulls each RSS/Atom feed (with a conditional-GET
cache), cross-checks the Hacker News front page via the Algolia API, then
normalizes every story into a NewsItem-shaped dict with deterministic
confidence and importance scores.

Output: data/runs/YYYY-MM-DD/news_raw.json  (a ranked candidate pool)

This stage never invents content and never calls an AI model. It only
collects, cleans, scores, and deduplicates. Malformed items are tolerated
here and removed later by validate_payloads.py against the Pydantic schema.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import feedparser

from schemas import SourceConfig, SourceType
from utils import (
    clean_html,
    extract_tags,
    fetch_url,
    get_logger,
    iso_now,
    load_yaml,
    ny_today,
    run_dir,
    truncate,
    write_json,
    DATA_DIR,
)

LOG = get_logger("collect_news")

HN_ALGOLIA_URL = "http://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30"

# Importance base weight per source type.
_TYPE_WEIGHT = {
    SourceType.OFFICIAL_BLOG: 0.70,
    SourceType.RELEASE_NOTES: 0.66,
    SourceType.PRODUCT_BLOG: 0.64,
    SourceType.RESEARCH: 0.60,
    SourceType.NEWS: 0.56,
    SourceType.AGGREGATOR: 0.42,
}

# Keep the raw candidate pool bounded; generate_post picks the final 3–7.
MAX_CANDIDATES = 45


# ──────────────────────────────────────────────────────────────────────
def _entry_datetime(entry: Any) -> datetime:
    """Best-effort published timestamp as tz-aware UTC."""
    for key in ("published_parsed", "updated_parsed"):
        st = getattr(entry, key, None) or (entry.get(key) if isinstance(entry, dict) else None)
        if st:
            try:
                return datetime(*st[:6], tzinfo=timezone.utc)
            except Exception:
                continue
    return datetime.now(timezone.utc)


def _recency_boost(published: datetime, lookback_hours: int) -> float:
    """0.0 (old) → ~0.2 (brand new), linear across the lookback window."""
    age_h = (datetime.now(timezone.utc) - published).total_seconds() / 3600.0
    if age_h <= 0:
        return 0.2
    frac = max(0.0, 1.0 - (age_h / max(lookback_hours, 1)))
    return round(0.2 * frac, 4)


def _clamp(x: float) -> float:
    return round(max(0.0, min(1.0, x)), 4)


def _normalize_entry(entry: Any, src: SourceConfig, lookback_hours: int) -> Optional[dict]:
    title = clean_html(getattr(entry, "title", "") or "")
    link = (getattr(entry, "link", "") or "").strip()
    if not title or not link.lower().startswith("http"):
        return None

    # Google News RSS proxies (e.g. the Anthropic entry) append " - Publisher"
    # to every title; strip that suffix so headlines read like the original.
    if "news.google.com" in (src.feed or "") and " - " in title:
        title = title.rsplit(" - ", 1)[0].strip() or title

    raw_summary = (
        getattr(entry, "summary", None)
        or getattr(entry, "description", None)
        or (entry.get("content", [{}])[0].get("value") if isinstance(entry, dict) else None)
        or ""
    )
    summary = truncate(clean_html(raw_summary), 480)
    published = _entry_datetime(entry)

    importance = _TYPE_WEIGHT.get(src.source_type, 0.5) + _recency_boost(published, lookback_hours)
    confidence = src.trust
    if summary:
        confidence += 0.02
    if published > datetime.now(timezone.utc) - timedelta(hours=24):
        confidence += 0.02

    return {
        "title": title,
        "summary": summary,
        "source_name": src.name,
        "source_url": link,
        "published_at": published.isoformat(),
        "category": src.category,
        "tags": extract_tags(f"{title} {summary}", extra=[src.category.replace('_', ' ').title()]),
        "confidence_score": _clamp(confidence),
        "importance_score": _clamp(importance),
        "source_type": src.source_type.value,
        "ai_generated_summary": None,
        "why_it_matters": None,
        "guid": (getattr(entry, "id", None) or link),
    }


def _collect_from_feed(src: SourceConfig, defaults: dict) -> list[dict]:
    if not src.feed:
        return []
    lookback = int(defaults.get("lookback_hours", 48))
    max_items = int(defaults.get("max_items_per_feed", 12))
    min_title = int(defaults.get("min_title_chars", 16))
    timeout = int(defaults.get("request_timeout", 20))
    ua = defaults.get("user_agent")

    raw = fetch_url(src.feed, timeout=timeout, user_agent=ua)
    if not raw:
        return []

    parsed = feedparser.parse(raw)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback)
    out: list[dict] = []
    for entry in parsed.entries[: max_items * 2]:
        item = _normalize_entry(entry, src, lookback)
        if not item:
            continue
        if len(item["title"]) < min_title:
            continue
        if datetime.fromisoformat(item["published_at"]) < cutoff:
            continue
        out.append(item)
        if len(out) >= max_items:
            break
    LOG.info("  %-32s %2d items", src.name, len(out))
    return out


def _collect_hacker_news(defaults: dict) -> list[dict]:
    """Front-page HN via Algolia. Points drive importance for cross-signal."""
    raw = fetch_url(HN_ALGOLIA_URL, timeout=int(defaults.get("request_timeout", 20)),
                    user_agent=defaults.get("user_agent"), use_cache=False)
    if not raw:
        LOG.warning("  Hacker News API unavailable")
        return []
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception as exc:
        LOG.warning("  HN parse error: %s", exc)
        return []

    lookback = int(defaults.get("lookback_hours", 48))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback)
    out: list[dict] = []
    for hit in data.get("hits", []):
        title = clean_html(hit.get("title") or "")
        if not title:
            continue
        url = (hit.get("url") or "").strip()
        if not url:
            url = f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        try:
            published = datetime.fromtimestamp(int(hit.get("created_at_i", 0)), tz=timezone.utc)
        except Exception:
            published = datetime.now(timezone.utc)
        if published < cutoff:
            continue
        points = int(hit.get("points") or 0)
        importance = _TYPE_WEIGHT[SourceType.AGGREGATOR] + min(points / 800.0, 0.25) \
            + _recency_boost(published, lookback)
        out.append({
            "title": title,
            "summary": truncate(clean_html(hit.get("story_text") or ""), 300),
            "source_name": "Hacker News",
            "source_url": url,
            "published_at": published.isoformat(),
            "category": "aggregators",
            "tags": extract_tags(title, extra=["Hacker News"]),
            "confidence_score": _clamp(0.55 + min(points / 2000.0, 0.15)),
            "importance_score": _clamp(importance),
            "source_type": SourceType.AGGREGATOR.value,
            "ai_generated_summary": None,
            "why_it_matters": None,
            "guid": f"hn-{hit.get('objectID')}",
        })
    LOG.info("  %-32s %2d items", "Hacker News (front page)", len(out))
    return out


# ──────────────────────────────────────────────────────────────────────
#  tetw.org cross-reference enrichment (NOT a sources.yml entry)
#
#  The Electric Typewriter (tetw.org) is a curated, largely EVERGREEN
#  long-form essay archive with no reliable per-item publish dates of its
#  own - running it through the normal feed path would filter it to zero
#  items every run. Instead, this step runs AFTER the normal collection
#  pass and depends on the day's candidates as input:
#
#    1. scrape tetw.org list page(s) for candidate outbound article links;
#    2. keep only links topically matching today's already-collected
#       candidates (tag phrases + title-token overlap);
#    3. fetch each match's UNDERLYING source page (tetw mostly links out
#       to NYT/Wired/New Yorker/etc.) and read that page's own publish date;
#    4. include the item only if that date is within lookback_hours -
#       topical match alone is NOT enough; stale items are discarded.
#
#  Expected behaviour: contributes rarely (the archive is evergreen and the
#  freshness gate is strict). Every failure degrades to skip-with-log; this
#  step must never fail the batch.
# ──────────────────────────────────────────────────────────────────────
TETW_PAGES = ["https://tetw.org/"]
TETW_MAX_ITEMS = 2          # cap per run - enrichment, not a firehose
TETW_MAX_DATE_PROBES = 8    # at most this many underlying-source fetches

_STOPWORDS = frozenset(
    "the a an and or but of for to in on with by from at as is are was were be "
    "been has have had how why what when where who which this that these those "
    "its it's about into over under after before between against more most new".split()
)

_DATE_PATTERNS = [
    r'"datePublished"\s*:\s*"([^"]+)"',                                  # JSON-LD
    r'property="article:published_time"\s+content="([^"]+)"',            # Open Graph
    r'content="([^"]+)"\s+property="article:published_time"',
    r'itemprop="datePublished"\s+content="([^"]+)"',
    r'<time[^>]+datetime="([^"]+)"',
]


def _meaningful_tokens(text: str) -> set[str]:
    return {
        w for w in "".join(c if c.isalnum() else " " for c in text.lower()).split()
        if len(w) > 3 and w not in _STOPWORDS
    }


def _extract_publish_date(html_text: str) -> Optional[datetime]:
    """Best-effort publish date of an article page (head metadata only)."""
    import re
    from dateutil import parser as dtparser

    head = html_text[:80_000]
    for pat in _DATE_PATTERNS:
        m = re.search(pat, head, re.I)
        if not m:
            continue
        try:
            dt = dtparser.parse(m.group(1))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            continue
    return None


def _collect_tetw_crossref(candidates: list[dict], defaults: dict) -> list[dict]:
    """Cross-reference tetw.org's curated lists against today's candidates."""
    from urllib.parse import urlparse

    from bs4 import BeautifulSoup

    lookback = int(defaults.get("lookback_hours", 48))
    timeout = int(defaults.get("request_timeout", 20))
    ua = defaults.get("user_agent")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback)

    # Today's topical fingerprint: tag phrases + title tokens.
    tag_phrases = {t.lower() for c in candidates for t in c.get("tags", []) if len(t) > 3}
    title_tokens: set[str] = set()
    for c in candidates:
        title_tokens |= _meaningful_tokens(c["title"])
    if not tag_phrases and not title_tokens:
        return []

    # 1. Scrape the list page(s) for outbound article links.
    entries: list[tuple[str, str]] = []  # (title, url)
    for page in TETW_PAGES:
        raw = fetch_url(page, timeout=timeout, user_agent=ua)
        if not raw:
            LOG.info("  tetw.org unreachable - skipping cross-ref")
            continue
        try:
            soup = BeautifulSoup(raw, "html.parser")
        except Exception as exc:
            LOG.warning("  tetw parse error: %s", exc)
            continue
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = " ".join(a.get_text(" ", strip=True).split())
            host = urlparse(href).netloc.lower()
            if not href.startswith("http") or "tetw.org" in host or not host:
                continue
            if len(text) < 16:  # nav chrome / "click through" links
                continue
            entries.append((text, href))

    if not entries:
        return []

    # 2. Topical match against today's signal.
    matched: list[tuple[str, str]] = []
    seen: set[str] = set()
    for title, url in entries:
        if url in seen:
            continue
        seen.add(url)
        tokens = _meaningful_tokens(title)
        overlap = len(tokens & title_tokens)
        phrase_hit = any(ph in title.lower() for ph in tag_phrases)
        if overlap >= 2 or phrase_hit:
            matched.append((title, url))
    LOG.info("  tetw.org: %d outbound links, %d topical matches", len(entries), len(matched))

    # 3+4. Verify the UNDERLYING source's own publish date; keep fresh only.
    out: list[dict] = []
    for title, url in matched[:TETW_MAX_DATE_PROBES]:
        raw = fetch_url(url, timeout=timeout, user_agent=ua)
        if not raw:
            LOG.info("    tetw target unreachable, skipping: %s", url)
            continue
        published = _extract_publish_date(raw.decode("utf-8", "replace"))
        if published is None:
            LOG.info("    no publish date found, skipping (freshness unprovable): %s", url)
            continue
        if published < cutoff:
            LOG.info("    stale (%s), discarding despite topical match: %s",
                     published.date().isoformat(), url)
            continue
        out.append({
            "title": title,
            "summary": "",
            "source_name": "The Electric Typewriter",
            "source_url": url,
            "published_at": published.isoformat(),
            "category": "aggregators",
            "tags": extract_tags(title, extra=["Long Read"]),
            "confidence_score": _clamp(0.58),
            "importance_score": _clamp(
                _TYPE_WEIGHT[SourceType.AGGREGATOR] + _recency_boost(published, lookback)
            ),
            "source_type": SourceType.AGGREGATOR.value,
            "ai_generated_summary": None,
            "why_it_matters": None,
            "guid": f"tetw-{url}",
        })
        if len(out) >= TETW_MAX_ITEMS:
            break
    LOG.info("  %-32s %2d items", "tetw.org (cross-ref)", len(out))
    return out


def _dedupe(items: list[dict]) -> list[dict]:
    """Drop duplicate URLs and near-duplicate titles, keeping the strongest."""
    items.sort(key=lambda x: x["importance_score"], reverse=True)
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    kept: list[dict] = []
    for it in items:
        url_key = it["source_url"].split("?")[0].rstrip("/").lower()
        title_key = "".join(ch for ch in it["title"].lower() if ch.isalnum())[:60]
        if url_key in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)
        kept.append(it)
    return kept


def main() -> int:
    today = ny_today()
    rundir = run_dir(today)
    LOG.info("Collecting news for %s", today.isoformat())

    config = load_yaml(DATA_DIR / "sources.yml") or {}
    defaults = config.get("defaults", {}) or {}

    # Validate source configs; skip (don't crash on) malformed entries.
    sources: list[SourceConfig] = []
    for raw_src in config.get("sources", []) or []:
        try:
            sc = SourceConfig(**raw_src)
            if sc.enabled:
                sources.append(sc)
        except Exception as exc:
            LOG.warning("skipping bad source %r: %s", raw_src.get("name", "?"), exc)

    LOG.info("Fetching %d sources…", len(sources))
    all_items: list[dict] = []
    for src in sources:
        try:
            all_items.extend(_collect_from_feed(src, defaults))
        except Exception as exc:  # one feed must never fail the batch
            LOG.warning("feed error for %s: %s", src.name, exc)

    # Cross-signal aggregator (HN) - independent of the RSS pass.
    try:
        all_items.extend(_collect_hacker_news(defaults))
    except Exception as exc:
        LOG.warning("HN error: %s", exc)

    deduped = _dedupe(all_items)[:MAX_CANDIDATES]

    # tetw.org cross-ref enrichment - needs the day's candidates as input,
    # so it runs after the normal pass (see the function's doc block).
    try:
        extra = _collect_tetw_crossref(deduped, defaults)
        if extra:
            deduped = _dedupe(deduped + extra)[:MAX_CANDIDATES]
    except Exception as exc:  # enrichment must never fail the batch
        LOG.warning("tetw cross-ref error: %s", exc)

    payload = {
        "generated_at": iso_now(),
        "post_date": today.isoformat(),
        "sources_checked": len(sources),
        "candidates": len(deduped),
        "items": deduped,
    }
    out_path = rundir / "news_raw.json"
    write_json(out_path, payload)
    LOG.info("Wrote %d candidate stories → %s", len(deduped), out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
