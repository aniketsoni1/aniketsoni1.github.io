"""
aggregate_week.py - BRONZE layer of the weekly Signal Perspective pipeline.

Reads the last LOOKBACK_DAYS of committed daily run payloads
(data/runs/YYYY-MM-DD/daily_signal_payload.json), and deterministically:

  1. collects every validated story of the week;
  2. picks the dominant theme by tag frequency (source-name tags excluded);
  3. orders candidate stories (on-theme first, by importance score);
  4. re-validates candidate source links and drops dead ones;
  5. writes data/runs/YYYY-MM-DD/perspective_week_payload.json - the single
     input consumed by the downstream validate/render stages.

No AI is involved at this layer. Exits non-zero if fewer than MIN_CITATIONS
stories survive link re-validation (nothing downstream should run).
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta

from utils import (
    RUNS_DIR,
    get_logger,
    ny_today,
    read_json,
    run_dir,
    validate_urls,
    write_json,
)

LOG = get_logger("aggregate_week")

LOOKBACK_DAYS = 7
MIN_CITATIONS = 2
MAX_CITATIONS = 6
MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _week_range_label(start: date, end: date) -> str:
    if start.month == end.month:
        return f"{MONTHS[start.month - 1]} {start.day}–{end.day}, {end.year}"
    return (
        f"{MONTHS[start.month - 1]} {start.day} – "
        f"{MONTHS[end.month - 1]} {end.day}, {end.year}"
    )


def _load_week(today: date) -> tuple[list[dict], list[date]]:
    """Return (stories, run_dates) from the last LOOKBACK_DAYS of payloads."""
    stories: list[dict] = []
    run_dates: list[date] = []
    for offset in range(LOOKBACK_DAYS):
        d = today - timedelta(days=offset)
        payload_path = RUNS_DIR / d.isoformat() / "daily_signal_payload.json"
        if not payload_path.exists():
            continue
        try:
            payload = read_json(payload_path)
        except Exception as exc:
            LOG.warning("unreadable payload for %s: %s", d, exc)
            continue
        run_dates.append(d)
        for item in payload.get("news_items", []):
            title = (item.get("title") or "").strip()
            url = (item.get("source_url") or "").strip()
            if not title or not url:
                continue
            stories.append(
                {
                    "date": d.isoformat(),
                    "title": title,
                    "url": url,
                    "source_name": (item.get("source_name") or "Source").strip(),
                    "tags": [t.strip() for t in item.get("tags", []) if t and t.strip()],
                    "summary": (
                        item.get("ai_generated_summary")
                        or item.get("original_summary")
                        or ""
                    ).strip(),
                    "why": (item.get("why_it_matters") or "").strip(),
                    "score": float(item.get("importance_score") or 0.0),
                }
            )
    return stories, sorted(run_dates)


def _pick_theme(stories: list[dict]) -> tuple[str, list[str], Counter]:
    """Dominant theme by tag frequency. Source-name tags are not themes."""
    source_names = {s["source_name"].casefold() for s in stories}
    counts: Counter = Counter()
    for s in stories:
        for t in s["tags"]:
            if t.casefold() not in source_names:
                counts[t] += 1
    if not counts:
        return "Technology", [], counts
    theme, _ = counts.most_common(1)[0]
    related = [t for t, _ in counts.most_common(6) if t != theme]
    return theme, related, counts


def _theme_stories(stories: list[dict], theme: str) -> list[dict]:
    """Stories tagged with the theme first (by score), then top remainder."""
    on_theme = sorted(
        (s for s in stories if theme in s["tags"]),
        key=lambda s: s["score"], reverse=True,
    )
    rest = sorted(
        (s for s in stories if theme not in s["tags"]),
        key=lambda s: s["score"], reverse=True,
    )
    seen: set = set()
    ordered = []
    for s in on_theme + rest:
        if s["url"] not in seen:
            seen.add(s["url"])
            ordered.append(s)
    return ordered


def main() -> int:
    today = ny_today()
    week_start = today - timedelta(days=LOOKBACK_DAYS - 1)
    rundir = run_dir(today)
    LOG.info("Aggregating week of %s → %s", week_start.isoformat(), today.isoformat())

    stories, run_dates = _load_week(today)
    LOG.info("Loaded %d stories from %d daily runs", len(stories), len(run_dates))
    if not stories:
        LOG.error("No committed daily payloads in the lookback window - nothing to aggregate.")
        return 1

    theme, related, counts = _pick_theme(stories)
    ordered = _theme_stories(stories, theme)

    candidates = ordered[: MAX_CITATIONS * 2]
    status = validate_urls([s["url"] for s in candidates])
    cited = [s for s in candidates if status.get(s["url"], False)][:MAX_CITATIONS]
    LOG.info("Citations: %d live of %d candidates", len(cited), len(candidates))
    if len(cited) < MIN_CITATIONS:
        LOG.error(
            "Only %d live citation(s) (< %d) - refusing to feed a weakly-sourced column downstream.",
            len(cited), MIN_CITATIONS,
        )
        return 1

    payload = {
        "post_date": today.isoformat(),
        "week_start": week_start.isoformat(),
        "week_label": _week_range_label(week_start, today),
        "theme": theme,
        "related_themes": related,
        "tag_counts": [{"tag": t, "count": c} for t, c in counts.most_common(6)],
        "stories_reviewed": len(stories),
        "runs_used": [d.isoformat() for d in run_dates],
        "sources_count": len({s["source_name"] for s in stories}),
        "citations": cited,
    }
    out = rundir / "perspective_week_payload.json"
    write_json(out, payload)
    LOG.info("Wrote bronze payload → %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
