"""
validate_payloads.py - the structured-data validation gate.

Runs after the collectors and before generation. It:
  * validates news_raw.json items against NewsItem, dropping malformed ones,
    enforcing numeric bounds, and writing the clean set to news_validated.json;
  * re-validates events_validated.json and history_validated.json against their
    schemas (idempotent belt-and-braces);
  * writes a machine-readable validation_report.json to the run directory.

Philosophy: this stage is self-healing, not fail-fast. A low news count is NOT
an error here - the Short Signal fallback in generate_post handles it. The hard
publish/no-publish decision lives in validate_post.py. This gate only fails if a
required payload file is missing or completely unreadable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from schemas import EventItem, HistoryItem, NewsItem, ValidationResult
from utils import get_logger, ny_today, read_json, run_dir, write_json

LOG = get_logger("validate_payloads")


def _load(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return read_json(path)
    except Exception as exc:
        LOG.error("unreadable JSON %s: %s", path, exc)
        return None


def _validate_news(rundir: Path) -> ValidationResult:
    res = ValidationResult(stage="news")
    data = _load(rundir / "news_raw.json")
    if data is None:
        return res.fail("news_raw.json missing or unreadable")

    kept: list[dict] = []
    for raw in data.get("items", []):
        try:
            item = NewsItem(**raw)
            kept.append(item.model_dump(mode="json"))
        except ValidationError as exc:
            res.dropped += 1
            res.warn(f"dropped news item: {exc.error_count()} error(s)")
        except Exception as exc:
            res.dropped += 1
            res.warn(f"dropped news item: {exc}")

    res.kept = len(kept)
    write_json(
        rundir / "news_validated.json",
        {
            "post_date": data.get("post_date", ny_today().isoformat()),
            "sources_checked": data.get("sources_checked", 0),
            "count": len(kept),
            "items": kept,
        },
    )
    if res.kept < 3:
        res.warn(f"only {res.kept} valid news items - Short Signal edition likely")
    return res


def _validate_events(rundir: Path) -> ValidationResult:
    res = ValidationResult(stage="events")
    data = _load(rundir / "events_validated.json")
    if data is None:
        return res.warn("events_validated.json missing - Event Radar may be empty")

    kept: list[dict] = []
    for raw in data.get("events", []):
        try:
            kept.append(EventItem(**raw).model_dump(mode="json"))
        except Exception as exc:
            res.dropped += 1
            res.warn(f"dropped event: {exc}")
    res.kept = len(kept)

    # Rewrite with only valid events (idempotent clean).
    data["events"] = kept
    data["count"] = len(kept)
    write_json(rundir / "events_validated.json", data)
    return res


def _validate_history(rundir: Path) -> ValidationResult:
    res = ValidationResult(stage="history")
    data = _load(rundir / "history_validated.json")
    if data is None:
        return res.warn("history_validated.json missing - history section may be empty")
    try:
        HistoryItem(**data.get("item", {}))
        res.kept = 1
    except Exception as exc:
        res.dropped += 1
        return res.fail(f"invalid history item: {exc}")
    return res


def main() -> int:
    today = ny_today()
    rundir = run_dir(today)
    LOG.info("Validating payloads for %s", today.isoformat())

    results = [
        _validate_news(rundir),
        _validate_events(rundir),
        _validate_history(rundir),
    ]

    for r in results:
        LOG.info(r.summary_line())

    report = {
        "post_date": today.isoformat(),
        "stages": [r.model_dump(mode="json") for r in results],
        "ok": all(r.ok for r in results),
    }
    write_json(rundir / "validation_report.json", report)

    # Only hard-fail if a stage marked itself not-ok (missing/corrupt required
    # data). Low counts are fine - the generator degrades gracefully.
    if not report["ok"]:
        LOG.error("payload validation reported hard errors")
        return 1
    LOG.info("Payload validation OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
