"""
collect_history.py — 'This Day in Computing History' selector.

Reads data/computing_history.yml and picks the single best milestone for the
current America/New_York date using a three-tier strategy:

  1. EXACT   — a milestone whose MM-DD equals today (highest importance wins).
  2. NEARBY  — the closest milestone in the SAME month within ±NEARBY_DAYS.
  3. FALLBACK— a deterministic rotation through the evergreen general_fallbacks.

Output: data/runs/YYYY-MM-DD/history_validated.json

The selector never fabricates a date: undated evergreen facts are only used as
tier-3 fallbacks, and their MM-DD stays null.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from schemas import HistoryItem
from utils import (
    DATA_DIR,
    get_logger,
    iso_now,
    load_yaml,
    ny_today,
    run_dir,
    write_json,
)

LOG = get_logger("collect_history")

NEARBY_DAYS = 6  # how far to reach within the same month for a near match


def _to_item(raw: dict) -> Optional[HistoryItem]:
    """Map a YAML record onto the HistoryItem schema (confidence→confidence_score)."""
    try:
        return HistoryItem(
            date=raw.get("date"),
            title=raw["title"],
            year=int(raw["year"]),
            description=raw["description"],
            category=raw.get("category", "history"),
            source_url=raw.get("source_url"),
            confidence_score=float(raw.get("confidence", 0.8)),
            importance=float(raw.get("importance", 0.7)),
        )
    except Exception as exc:
        LOG.warning("skipping malformed history record %r: %s", raw.get("title", "?"), exc)
        return None


def _day_delta(mmdd: str, today: date) -> Optional[int]:
    """Absolute day distance within the same month; None if different month."""
    try:
        mm, dd = (int(x) for x in mmdd.split("-"))
    except Exception:
        return None
    if mm != today.month:
        return None
    return abs(dd - today.day)


def select_history(today: date, milestones: list[HistoryItem], fallbacks: list[HistoryItem]) -> tuple[HistoryItem, str]:
    key = f"{today.month:02d}-{today.day:02d}"

    # Tier 1 — exact date.
    exact = [m for m in milestones if m.date == key]
    if exact:
        exact.sort(key=lambda m: (m.importance, m.confidence_score), reverse=True)
        return exact[0], "exact"

    # Tier 2 — nearest in the same month.
    scored: list[tuple[int, HistoryItem]] = []
    for m in milestones:
        if not m.date:
            continue
        delta = _day_delta(m.date, today)
        if delta is not None and delta <= NEARBY_DAYS:
            scored.append((delta, m))
    if scored:
        scored.sort(key=lambda t: (t[0], -t[1].importance))
        return scored[0][1], "nearby"

    # Tier 3 — deterministic rotation through evergreen fallbacks.
    if fallbacks:
        idx = today.timetuple().tm_yday % len(fallbacks)
        return fallbacks[idx], "fallback"

    # Last resort — a hardcoded, always-true fact so the section never breaks.
    return (
        HistoryItem(
            title="The stored-program computer",
            year=1945,
            description=(
                "The stored-program concept — instructions and data sharing the same "
                "memory — underlies essentially every computer in use today."
            ),
            category="hardware",
            source_url="https://en.wikipedia.org/wiki/Von_Neumann_architecture",
            confidence_score=0.9,
            importance=0.8,
        ),
        "hardcoded",
    )


def main() -> int:
    today = ny_today()
    rundir = run_dir(today)
    LOG.info("Selecting computing history for %s", today.isoformat())

    cfg = load_yaml(DATA_DIR / "computing_history.yml") or {}
    milestones = [i for i in (_to_item(r) for r in cfg.get("milestones", []) or []) if i]
    fallbacks = [i for i in (_to_item(r) for r in cfg.get("general_fallbacks", []) or []) if i]

    item, match_type = select_history(today, milestones, fallbacks)
    LOG.info("Selected (%s): %s (%s)", match_type, item.title, item.year)

    payload = {
        "generated_at": iso_now(),
        "post_date": today.isoformat(),
        "match_type": match_type,
        "history_items_checked": len(milestones) + len(fallbacks),
        "item": item.model_dump(mode="json"),
    }
    out_path = rundir / "history_validated.json"
    write_json(out_path, payload)
    LOG.info("Wrote history → %s", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
