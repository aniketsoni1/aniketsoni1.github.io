"""
generate_post.py — deterministic rendering + publishing layer.

Pipeline position: runs after validate_payloads.py. It does NOT invent
structure or facts. It:

  1. loads validated JSON payloads (news / events / history);
  2. ranks news, validates each candidate's link, and drops dead-link stories;
  3. decides the edition (>=3 valid stories = standard, else Short Signal);
  4. calls summarize_with_ai ONLY for per-item summary + 'why it matters',
     plus the intro and takeaway language (all source-grounded, with a
     deterministic fallback);
  5. renders templates/daily_signal.md.j2 into a Jekyll post;
  6. writes _posts/YYYY-MM-DD-daily-tech-signal.md, daily_signal_payload.json,
     and provenance.json.

If no AI provider is configured, everything still renders from deterministic,
source-tied text.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

import summarize_with_ai as ai
from schemas import (
    DailySignalPayload,
    Edition,
    EventItem,
    EventState,
    HistoryItem,
    NewsItem,
    ProvenanceManifest,
)
from utils import (
    POSTS_DIR,
    TEMPLATES_DIR,
    display_date,
    get_logger,
    ny_now,
    ny_today,
    read_json,
    run_dir,
    validate_urls,
    write_json,
)

LOG = get_logger("generate_post")

MIN_STORIES = 3         # below this, the brief runs as a Short Signal edition
MIN_TOP_SIGNALS = 7     # daily target floor for Top Technology Signals
MAX_TOP_SIGNALS = 15    # daily ceiling
LINK_CHECK_POOL = 24    # validate links on at most this many top candidates


def _daily_signal_cap(d: date) -> int:
    """
    Vary the day's Top Technology Signals count between MIN_TOP_SIGNALS and
    MAX_TOP_SIGNALS. Seeded by the date, NOT true randomness: re-running the
    same day's pipeline reproduces the same post (the repo's determinism
    rule). If fewer stories survive link review than the cap, we publish
    what survived — an honest shorter list beats padding.
    """
    import random

    return random.Random(d.toordinal()).randint(MIN_TOP_SIGNALS, MAX_TOP_SIGNALS)

AUTHOR = "Aniket Abhishek Soni"
DISCLAIMER = "This daily brief is AI-assisted and source-reviewed for public technology awareness."
DESCRIPTION = (
    "Daily brief on AI, data engineering, cloud platforms, technology events, and computing history."
)
MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


# ──────────────────────────────────────────────────────────────────────
#  Small formatting / safety helpers
# ──────────────────────────────────────────────────────────────────────
def _liquid_safe(text: Optional[str]) -> str:
    """Neutralize any Liquid delimiters so Jekyll won't try to parse them."""
    if not text:
        return ""
    return (
        text.replace("{{", "{ {").replace("}}", "} }")
        .replace("{%", "{ %").replace("%}", "% }")
    )


def _fmt_date_long(d: date) -> str:
    return f"{MONTHS[d.month - 1]} {d.day}, {d.year}"


def _fmt_published(dt_iso: str) -> str:
    try:
        dt = datetime.fromisoformat(dt_iso)
        return f"{MONTHS[dt.month - 1][:3]} {dt.day}, {dt.year}"
    except Exception:
        return ""


def _fmt_event_dates(start: date, end: date) -> str:
    if start == end:
        return _fmt_date_long(start)
    if start.year == end.year and start.month == end.month:
        return f"{MONTHS[start.month - 1]} {start.day}–{end.day}, {start.year}"
    if start.year == end.year:
        return f"{MONTHS[start.month - 1]} {start.day} – {MONTHS[end.month - 1]} {end.day}, {start.year}"
    return f"{_fmt_date_long(start)} – {_fmt_date_long(end)}"


def _front_matter_date(post_date: date) -> str:
    """'YYYY-MM-DD 09:00:00 -0400/-0500' with the correct DST offset for NY."""
    from utils import NY_TZ

    dt = datetime(post_date.year, post_date.month, post_date.day, 9, 0, 0, tzinfo=NY_TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S %z")


def _source_label(url: Optional[str]) -> str:
    if not url:
        return "Reference"
    host = (urlparse(url).netloc or "").replace("www.", "")
    known = {
        "en.wikipedia.org": "Wikipedia",
        "arxiv.org": "arXiv",
    }
    return known.get(host, host or "Reference")


# ──────────────────────────────────────────────────────────────────────
#  Load validated payloads
# ──────────────────────────────────────────────────────────────────────
def _load_news(rundir: Path) -> list[NewsItem]:
    path = rundir / "news_validated.json"
    if not path.exists():
        return []
    items = []
    for raw in read_json(path).get("items", []):
        try:
            items.append(NewsItem(**raw))
        except Exception as exc:
            LOG.warning("skipping unloadable news item: %s", exc)
    items.sort(key=lambda i: i.importance_score, reverse=True)
    return items


def _load_events(rundir: Path) -> tuple[list[EventItem], int]:
    path = rundir / "events_validated.json"
    if not path.exists():
        return [], 0
    data = read_json(path)
    events = []
    for raw in data.get("events", []):
        try:
            events.append(EventItem(**raw))
        except Exception:
            continue
    return events, int(data.get("events_checked", len(events)))


def _load_history(rundir: Path) -> tuple[Optional[HistoryItem], int]:
    path = rundir / "history_validated.json"
    if not path.exists():
        return None, 0
    data = read_json(path)
    try:
        return HistoryItem(**data.get("item", {})), int(data.get("history_items_checked", 1))
    except Exception:
        return None, 0


# ──────────────────────────────────────────────────────────────────────
#  Story selection with link validation
# ──────────────────────────────────────────────────────────────────────
def _select_stories(news: list[NewsItem], cap: int) -> tuple[list[NewsItem], int, int]:
    """Validate links on the top candidates; keep survivors up to the day's cap."""
    pool = news[:LINK_CHECK_POOL]
    if not pool:
        return [], 0, 0
    link_status = validate_urls([n.source_url for n in pool])
    ok = sum(1 for v in link_status.values() if v)
    failed = sum(1 for v in link_status.values() if not v)
    survivors = [n for n in pool if link_status.get(n.source_url, False)]
    LOG.info("Link check: %d ok, %d failed (of %d candidates)", ok, failed, len(pool))
    return survivors[:cap], ok, failed


# ──────────────────────────────────────────────────────────────────────
#  Deterministic 'AI & Data Engineering Impact' assembly
# ──────────────────────────────────────────────────────────────────────
def _build_impact(items: list[NewsItem]) -> str:
    if not items:
        return (
            "With few validated signals today, the practical guidance is simply to keep "
            "watching the primary sources below and revisit tomorrow's brief."
        )
    themes = sorted({t for i in items for t in i.tags})
    theme_str = ", ".join(themes[:6]) if themes else "today's stories"
    lead = items[0]
    return (
        f"Read together, today's stories cluster around {theme_str}. "
        f"For **data engineers**, the operative question is what these changes mean for "
        f"pipeline reliability, cost, and the interfaces between storage, compute, and "
        f"orchestration. For **AI engineers**, watch how model and tooling shifts affect "
        f"evaluation, latency, and deployment surface. **Cloud architects and enterprise "
        f"leaders** should read the same items through the lens of lock-in, security, and "
        f"total cost of ownership, while **researchers and developers** get early signal on "
        f"where the practical frontier is moving. The lead item — "
        f"“{_liquid_safe(lead.title)}” — is a good starting point."
    )


# ──────────────────────────────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────────────────────────────
def main() -> int:
    today = ny_today()
    rundir = run_dir(today)
    LOG.info("Generating post for %s", today.isoformat())

    news = _load_news(rundir)
    events, events_checked = _load_events(rundir)
    history, history_checked = _load_history(rundir)

    cap = _daily_signal_cap(today)
    selected, links_ok, links_failed = _select_stories(news, cap)
    edition = Edition.STANDARD if len(selected) >= MIN_STORIES else Edition.SHORT_SIGNAL
    LOG.info("Edition: %s (%d stories selected, today's cap %d)", edition.value, len(selected), cap)

    # ── AI summarization (or deterministic fallback) ──
    provider = ai.get_provider()
    for item in selected:
        summary, why = ai.summarize_news_item(item, provider)
        item.ai_generated_summary = summary
        item.why_it_matters = why

    intro = ai.write_intro(selected, events, history, provider)
    takeaway = ai.write_takeaway(selected, provider)
    provider_name, model_name, fallback_used = ai.provider_info(provider)

    # ── Optional AI hero image (generate_hero_image.py runs before us and
    #    leaves a manifest; a missing/failed image simply means no front
    #    matter `image:` — never an error here). ──
    hero_image = None
    hero_manifest_path = rundir / "hero_image.json"
    if hero_manifest_path.exists():
        try:
            hm = read_json(hero_manifest_path)
            if hm.get("path"):
                hero_image = {
                    "path": hm["path"],
                    "alt": hm.get("alt") or "Abstract artwork for today's Daily Tech Signal",
                    "provider": hm.get("provider") or "unknown",
                }
                LOG.info("Hero image attached (%s): %s", hero_image["provider"], hero_image["path"])
        except Exception as exc:
            LOG.warning("hero manifest unreadable, post ships without image: %s", exc)

    # ── Assemble the structured payload (audit + template input) ──
    all_tags = []
    for i in selected:
        for t in i.tags:
            clean = t.replace(",", "").replace("[", "").replace("]", "").strip()
            if clean and clean not in all_tags:
                all_tags.append(clean)
    tags = all_tags[:10] or ["Technology"]

    payload = DailySignalPayload(
        post_date=today,
        display_date=display_date(today),
        title=f"The Daily Tech Signal — {display_date(today)}",
        edition=edition,
        opening_summary=intro,
        news_items=selected,
        events=events,
        history_item=history,
        takeaway=takeaway,
        categories=["AI", "Data Engineering", "Technology"],
        tags=tags,
    )
    write_json(rundir / "daily_signal_payload.json", payload)

    # ── Build the template context (all pre-formatted, Liquid-safe) ──
    news_ctx = [
        {
            "title": _liquid_safe(i.title),
            "url": i.source_url,
            "source_name": _liquid_safe(i.source_name),
            "published_display": _fmt_published(i.published_at.isoformat()),
            "summary": _liquid_safe(i.best_summary),
            "why_it_matters": _liquid_safe(i.why_it_matters or ""),
        }
        for i in selected
    ]

    def _evt_ctx(states: list[EventState]):
        out = []
        for e in payload.events:
            if e.event_state in states:
                name = _liquid_safe(e.event_name)
                organizer = _liquid_safe(e.organizer)
                dates = _fmt_event_dates(e.start_date, e.end_date)
                location = _liquid_safe(e.location)
                summary = _liquid_safe(e.summary)
                line = f"**[{name}]({e.event_url})** — {organizer} · {dates} · {location}"
                if summary:
                    line += f" — {summary}"
                out.append({"line": line})
        return out

    events_ctx = {
        "happening_today": _evt_ctx([EventState.HAPPENING_TODAY]),
        "upcoming": _evt_ctx([EventState.UPCOMING]),
        "recent": _evt_ctx([EventState.RECENT]),
    }

    history_ctx = None
    if history:
        if history.date:
            mm, dd = (int(x) for x in history.date.split("-"))
            hist_when = f"{MONTHS[mm - 1]} {dd}, {history.year}"
        else:
            hist_when = str(history.year)
        history_ctx = {
            "headline": _liquid_safe(f"{hist_when} — {history.title}"),
            "description": _liquid_safe(history.description),
            "source_url": history.source_url,
            "source_label": _source_label(history.source_url),
        }

    context = {
        "title": payload.title,
        "date_fm": _front_matter_date(today),
        "author": AUTHOR,
        "categories": payload.categories,
        "tags": payload.tags,
        "description": DESCRIPTION,
        "edition": edition.value,
        "is_short": edition == Edition.SHORT_SIGNAL,
        "hero_image": hero_image,
        "opening_summary": _liquid_safe(intro),
        "news_items": news_ctx,
        "impact": _build_impact(selected),
        "events": events_ctx,
        "history": history_ctx,
        "takeaway": _liquid_safe(takeaway),
        "disclaimer": DISCLAIMER,
    }

    # ── Render ──
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(enabled_extensions=(), default=False),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    template = env.get_template("daily_signal.md.j2")
    markdown = template.render(**context)

    post_path = POSTS_DIR / f"{today.isoformat()}-daily-tech-signal.md"
    post_path.write_text(markdown, encoding="utf-8")
    LOG.info("Wrote post → %s (%d chars)", post_path, len(markdown))

    # ── Provenance manifest ──
    sources_used = len({i.source_name for i in selected})
    manifest = ProvenanceManifest(
        post_date=today,
        generated_at=ny_now(),
        model_provider=provider_name,
        model_name=model_name,
        fallback_used=fallback_used,
        sources_checked=read_json(rundir / "news_validated.json").get("sources_checked", 0)
        if (rundir / "news_validated.json").exists() else 0,
        sources_used=sources_used,
        links_validated=links_ok,
        links_failed=links_failed,
        events_checked=events_checked,
        history_items_checked=history_checked,
        output_post_path=str(post_path.relative_to(POSTS_DIR.parent)),
        validation_status="generated",
        edition=edition,
        run_dir=str(rundir),
    )
    manifest.add_note(f"selected {len(selected)} stories; edition={edition.value}")
    write_json(rundir / "provenance.json", manifest)
    LOG.info("Wrote provenance → %s", rundir / "provenance.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
