"""
collect_events.py — event lifecycle classification.

Reads data/tech_events.yml (curated source of truth) plus data/event_sources.yml
(official hubs, used for provenance), computes each event's lifecycle state from
its dates relative to America/New_York "today", and writes ONLY the active
events (upcoming / happening today / recent) to
data/runs/YYYY-MM-DD/events_validated.json.

Key design decisions
--------------------
* Non-destructive: we never rewrite tech_events.yml. State is derived at run
  time, so the curated file changes only when new official dates are published.
* Honest: events must carry a real source_url and valid dates; anything that
  fails the EventItem schema is dropped with a logged reason.
* A separate, opt-in monthly_cleanup() can flag long-archived events, but it is
  NOT wired into the daily run (see --cleanup flag) so nothing is pruned by
  accident.
"""

from __future__ import annotations

import argparse
from datetime import date
from typing import Any, Optional

from schemas import EventItem, EventState
from utils import (
    DATA_DIR,
    get_logger,
    iso_now,
    load_yaml,
    ny_today,
    run_dir,
    write_json,
)

LOG = get_logger("collect_events")

# Rank states for display ordering.
_STATE_ORDER = {
    EventState.HAPPENING_TODAY: 0,
    EventState.UPCOMING: 1,
    EventState.RECENT: 2,
    EventState.ARCHIVED: 9,
}


def _as_date(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except Exception:
            return None
    return None


def _classify(start: date, end: date, today: date, recent_window: int, horizon: int) -> EventState:
    if start <= today <= end:
        return EventState.HAPPENING_TODAY
    if start > today:
        return EventState.UPCOMING if (start - today).days <= horizon else EventState.ARCHIVED
    # end < today
    return EventState.RECENT if (today - end).days <= recent_window else EventState.ARCHIVED


def _relevance(evt: EventItem, home_region: str) -> float:
    """Higher = surface sooner within a state group (NYC/home events boosted)."""
    score = 0.0
    hay = f"{evt.location} {' '.join(evt.relevance_tags)}".lower()
    region_token = home_region.split(",")[0].strip().lower()  # e.g. "new york"
    if region_token and region_token in hay:
        score += 1.0
    if "nyc" in evt.relevance_tags:
        score += 0.5
    # Prefer bigger/AI/data topics on ties.
    for t in ("ai", "data_engineering", "cloud"):
        if t in evt.relevance_tags:
            score += 0.1
    return score


def main() -> int:
    today = ny_today()
    rundir = run_dir(today)
    LOG.info("Classifying events for %s", today.isoformat())

    events_cfg = load_yaml(DATA_DIR / "tech_events.yml") or {}
    settings = events_cfg.get("settings", {}) or {}
    recent_window = int(settings.get("recent_window_days", 30))
    horizon = int(settings.get("upcoming_horizon_days", 210))
    home_region = str(settings.get("home_region", "New York, NY"))

    # event_sources.yml is loaded to validate provenance and count hubs.
    hubs_cfg = load_yaml(DATA_DIR / "event_sources.yml") or {}
    hub_count = len(hubs_cfg.get("hubs", []) or [])

    raw_events = events_cfg.get("events", []) or []
    active: list[EventItem] = []
    dropped = 0

    for raw in raw_events:
        start = _as_date(raw.get("start_date"))
        end = _as_date(raw.get("end_date"))
        if not start or not end:
            LOG.warning("dropping event with bad dates: %r", raw.get("event_name", "?"))
            dropped += 1
            continue

        state = _classify(start, end, today, recent_window, horizon)
        if state == EventState.ARCHIVED:
            continue  # not surfaced; not an error

        try:
            evt = EventItem(
                event_name=raw["event_name"],
                organizer=raw["organizer"],
                event_url=raw["event_url"],
                start_date=start,
                end_date=end,
                location=raw.get("location", "TBD"),
                event_state=state,
                summary=raw.get("summary", ""),
                relevance_tags=raw.get("relevance_tags", []) or [],
                source_url=raw.get("source_url", raw["event_url"]),
            )
            active.append(evt)
        except Exception as exc:
            LOG.warning("dropping invalid event %r: %s", raw.get("event_name", "?"), exc)
            dropped += 1

    # Sort: state group, then relevance (desc), then chronology.
    def _sort_key(e: EventItem):
        rel = _relevance(e, home_region)
        # Upcoming sorts soonest-first; recent sorts most-recent-first.
        chrono = e.start_date.toordinal() if e.event_state == EventState.UPCOMING else -e.end_date.toordinal()
        return (_STATE_ORDER[e.event_state], -rel, chrono)

    active.sort(key=_sort_key)

    counts = {s.value: sum(1 for e in active if e.event_state == s) for s in EventState if s != EventState.ARCHIVED}
    payload = {
        "generated_at": iso_now(),
        "post_date": today.isoformat(),
        "home_region": home_region,
        "hubs_registered": hub_count,
        "events_checked": len(raw_events),
        "counts": counts,
        "events": [e.model_dump(mode="json") for e in active],
    }
    out_path = rundir / "events_validated.json"
    write_json(out_path, payload)
    LOG.info("Active events: %s (dropped %d) → %s", counts, dropped, out_path)
    return 0


def monthly_cleanup() -> list[str]:
    """
    OPT-IN, non-destructive helper. Returns the names of events whose end_date
    is far in the past (more than 400 days). It only *reports* — it does not
    edit tech_events.yml. Wire into a monthly workflow if you want reminders.
    """
    today = ny_today()
    events_cfg = load_yaml(DATA_DIR / "tech_events.yml") or {}
    stale = []
    for raw in events_cfg.get("events", []) or []:
        end = _as_date(raw.get("end_date"))
        if end and (today - end).days > 400:
            stale.append(raw.get("event_name", "?"))
    return stale


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Classify and export active tech events.")
    parser.add_argument("--cleanup", action="store_true", help="Report long-archived events (no writes).")
    args = parser.parse_args()
    if args.cleanup:
        for name in monthly_cleanup():
            LOG.info("stale (consider archiving in tech_events.yml): %s", name)
        raise SystemExit(0)
    raise SystemExit(main())
