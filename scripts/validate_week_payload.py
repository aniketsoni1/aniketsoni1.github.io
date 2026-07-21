"""
validate_week_payload.py - SILVER layer of the weekly Signal Perspective
pipeline: a schema gate on the aggregated week payload, mirroring
validate_payloads.py in the daily engine.

Checks data/runs/YYYY-MM-DD/perspective_week_payload.json with Pydantic:
required fields, sane counts, valid citation URLs, dates in ISO form, and
the MIN_CITATIONS floor. Exit 0 = payload safe for the render stage.
"""

from __future__ import annotations

import sys
from datetime import date

from pydantic import BaseModel, Field, HttpUrl, field_validator

from utils import get_logger, ny_today, read_json, run_dir

LOG = get_logger("validate_week_payload")

MIN_CITATIONS = 2
MAX_CITATIONS = 6
LOOKBACK_DAYS = 7


class WeekCitation(BaseModel):
    date: date
    title: str = Field(min_length=4, max_length=400)
    url: HttpUrl
    source_name: str = Field(min_length=1, max_length=120)
    tags: list[str] = []
    summary: str = ""
    why: str = ""
    score: float = 0.0


class TagCount(BaseModel):
    tag: str = Field(min_length=1, max_length=80)
    count: int = Field(ge=1)


class WeekPayload(BaseModel):
    post_date: date
    week_start: date
    week_label: str = Field(min_length=6, max_length=80)
    theme: str = Field(min_length=2, max_length=80)
    related_themes: list[str] = []
    tag_counts: list[TagCount] = Field(min_length=1)
    stories_reviewed: int = Field(ge=1)
    runs_used: list[date] = Field(min_length=1, max_length=LOOKBACK_DAYS)
    sources_count: int = Field(ge=1)
    citations: list[WeekCitation] = Field(min_length=MIN_CITATIONS, max_length=MAX_CITATIONS)

    @field_validator("week_start")
    @classmethod
    def _week_start_before_post(cls, v, info):
        post = info.data.get("post_date")
        if post and v > post:
            raise ValueError("week_start is after post_date")
        return v


def main() -> int:
    today = ny_today()
    path = run_dir(today, create=False) / "perspective_week_payload.json"
    if not path.exists():
        LOG.error("Bronze payload missing: %s", path)
        return 1

    try:
        payload = WeekPayload(**read_json(path))
    except Exception as exc:
        LOG.error("WEEK PAYLOAD REJECTED - schema violations:\n%s", exc)
        print(f"  ✗ {exc}", file=sys.stderr)
        return 1

    if payload.post_date != today:
        LOG.error("payload post_date %s != today %s", payload.post_date, today)
        return 1

    LOG.info(
        "WEEK PAYLOAD APPROVED - theme=%r, %d citations, %d stories from %d runs",
        payload.theme, len(payload.citations), payload.stories_reviewed, len(payload.runs_used),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
