"""
schemas.py - the single source of truth for every data contract in the
Daily Tech Signal pipeline.

Design intent
-------------
This pipeline is schema-first and validation-first. Nothing moves between
stages as a loose dict; everything is a Pydantic model. That gives us:

  * one place to define required fields, bounds, and coercions;
  * automatic rejection of malformed items (self-healing at the seams);
  * deterministic JSON round-tripping for the per-run audit trail.

All models target Pydantic v2. URLs are stored as ``str`` (validated to be
http/https) rather than ``HttpUrl`` so the JSON artifacts stay plain and the
downstream link-checker can operate on ordinary strings.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

_HTTP_RE = re.compile(r"^https?://", re.IGNORECASE)


# ──────────────────────────────────────────────────────────────────────
#  Enumerations
# ──────────────────────────────────────────────────────────────────────
class SourceType(str, Enum):
    """How much editorial trust a source category carries."""

    OFFICIAL_BLOG = "official_blog"
    PRODUCT_BLOG = "product_blog"
    RESEARCH = "research"
    NEWS = "news"
    AGGREGATOR = "aggregator"
    RELEASE_NOTES = "release_notes"


class EventState(str, Enum):
    """Lifecycle state derived from an event's dates vs. 'today'."""

    UPCOMING = "upcoming"
    HAPPENING_TODAY = "happening_today"
    RECENT = "recent"
    ARCHIVED = "archived"


class Edition(str, Enum):
    """Which template variant a given day produces."""

    STANDARD = "standard"
    SHORT_SIGNAL = "short_signal"


# ──────────────────────────────────────────────────────────────────────
#  Shared validators (mixed in where useful)
# ──────────────────────────────────────────────────────────────────────
def _require_http(value: str, field: str) -> str:
    value = (value or "").strip()
    if not _HTTP_RE.match(value):
        raise ValueError(f"{field} must be an http(s) URL, got: {value!r}")
    return value


# ──────────────────────────────────────────────────────────────────────
#  SourceConfig - one entry in data/sources.yml
# ──────────────────────────────────────────────────────────────────────
class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(min_length=2)
    category: str = Field(min_length=2)
    source_type: SourceType
    feed: Optional[str] = None
    homepage: str
    trust: float = Field(ge=0.0, le=1.0, default=0.6)
    enabled: bool = True

    @field_validator("homepage")
    @classmethod
    def _v_homepage(cls, v: str) -> str:
        return _require_http(v, "homepage")

    @field_validator("feed")
    @classmethod
    def _v_feed(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, "", "null"):
            return None
        return _require_http(v, "feed")


# ──────────────────────────────────────────────────────────────────────
#  NewsItem - one validated story
# ──────────────────────────────────────────────────────────────────────
class NewsItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=8)
    summary: str = Field(default="", description="Cleaned source description/abstract.")
    source_name: str = Field(min_length=2)
    source_url: str
    published_at: datetime
    category: str = Field(min_length=2)
    tags: list[str] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)
    importance_score: float = Field(ge=0.0, le=1.0)
    source_type: SourceType

    # Filled by the AI summarization layer (or deterministic fallback).
    ai_generated_summary: Optional[str] = None
    why_it_matters: Optional[str] = None

    # Provenance helpers (not required by spec, but cheap and useful).
    guid: Optional[str] = None

    @field_validator("source_url")
    @classmethod
    def _v_source_url(cls, v: str) -> str:
        return _require_http(v, "source_url")

    @field_validator("published_at")
    @classmethod
    def _v_published(cls, v: datetime) -> datetime:
        # Normalize to timezone-aware UTC so sorting/serialization is stable.
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v.astimezone(timezone.utc)

    @field_validator("tags")
    @classmethod
    def _v_tags(cls, v: list[str]) -> list[str]:
        seen, out = set(), []
        for t in v:
            t = (t or "").strip()
            key = t.lower()
            if t and key not in seen:
                seen.add(key)
                out.append(t)
        return out[:12]

    @property
    def best_summary(self) -> str:
        """Prefer AI summary, fall back to cleaned source summary."""
        return (self.ai_generated_summary or self.summary or self.title).strip()


# ──────────────────────────────────────────────────────────────────────
#  EventItem - one classified event
# ──────────────────────────────────────────────────────────────────────
class EventItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_name: str = Field(min_length=3)
    organizer: str = Field(min_length=2)
    event_url: str
    start_date: date
    end_date: date
    location: str = Field(default="TBD")
    event_state: EventState
    summary: str = Field(default="")
    relevance_tags: list[str] = Field(default_factory=list)
    source_url: str

    @field_validator("event_url")
    @classmethod
    def _v_event_url(cls, v: str) -> str:
        return _require_http(v, "event_url")

    @field_validator("source_url")
    @classmethod
    def _v_src_url(cls, v: str) -> str:
        return _require_http(v, "source_url")

    @model_validator(mode="after")
    def _v_dates(self) -> "EventItem":
        if self.end_date < self.start_date:
            raise ValueError(
                f"end_date {self.end_date} precedes start_date {self.start_date} "
                f"for event {self.event_name!r}"
            )
        return self


# ──────────────────────────────────────────────────────────────────────
#  HistoryItem - one 'this day in computing history' fact
# ──────────────────────────────────────────────────────────────────────
class HistoryItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # "MM-DD"; None for evergreen general_fallbacks entries.
    date: Optional[str] = None
    title: str = Field(min_length=4)
    year: int = Field(ge=1800, le=2100)
    description: str = Field(min_length=10)
    category: str = Field(min_length=2)
    source_url: Optional[str] = None
    confidence_score: float = Field(ge=0.0, le=1.0, default=0.8)
    importance: float = Field(ge=0.0, le=1.0, default=0.7)

    @field_validator("date")
    @classmethod
    def _v_date(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, "", "null"):
            return None
        if not re.fullmatch(r"\d{2}-\d{2}", v):
            raise ValueError(f"history date must be 'MM-DD', got {v!r}")
        mm, dd = (int(x) for x in v.split("-"))
        if not (1 <= mm <= 12 and 1 <= dd <= 31):
            raise ValueError(f"history date out of range: {v!r}")
        return v

    @field_validator("source_url")
    @classmethod
    def _v_src(cls, v: Optional[str]) -> Optional[str]:
        if v in (None, "", "null"):
            return None
        return _require_http(v, "source_url")


# ──────────────────────────────────────────────────────────────────────
#  DailySignalPayload - the rendered post's structured input
# ──────────────────────────────────────────────────────────────────────
class DailySignalPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    post_date: date
    display_date: str
    title: str
    edition: Edition = Edition.STANDARD

    opening_summary: Optional[str] = None
    news_items: list[NewsItem] = Field(default_factory=list)
    events: list[EventItem] = Field(default_factory=list)
    history_item: Optional[HistoryItem] = None
    takeaway: Optional[str] = None

    categories: list[str] = Field(default_factory=lambda: ["AI", "Data Engineering", "Technology"])
    tags: list[str] = Field(default_factory=list)
    disclaimer: str = (
        "This daily brief is AI-assisted and source-reviewed for public technology awareness."
    )

    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ── Convenience groupings for the template ──
    def events_by_state(self, state: EventState) -> list[EventItem]:
        return [e for e in self.events if e.event_state == state]

    @property
    def is_short(self) -> bool:
        return self.edition == Edition.SHORT_SIGNAL


# ──────────────────────────────────────────────────────────────────────
#  ProvenanceManifest - the per-run audit record
# ──────────────────────────────────────────────────────────────────────
class ProvenanceManifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    post_date: date
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_provider: str = "none"
    model_name: str = "none"
    fallback_used: bool = False

    sources_checked: int = 0
    sources_used: int = 0
    links_validated: int = 0
    links_failed: int = 0
    events_checked: int = 0
    history_items_checked: int = 0

    output_post_path: Optional[str] = None
    validation_status: str = "pending"  # pending | passed | failed | short_signal

    # Extra, non-spec fields for debugging (audit-only).
    edition: Edition = Edition.STANDARD
    run_dir: Optional[str] = None
    notes: list[str] = Field(default_factory=list)

    def add_note(self, note: str) -> None:
        self.notes.append(note)


# ──────────────────────────────────────────────────────────────────────
#  ValidationResult - returned by each validation gate
# ──────────────────────────────────────────────────────────────────────
class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stage: str
    ok: bool = True
    kept: int = 0
    dropped: int = 0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def fail(self, msg: str) -> "ValidationResult":
        self.ok = False
        self.errors.append(msg)
        return self

    def warn(self, msg: str) -> "ValidationResult":
        self.warnings.append(msg)
        return self

    def summary_line(self) -> str:
        status = "OK" if self.ok else "FAIL"
        return (
            f"[{status}] {self.stage}: kept={self.kept} dropped={self.dropped} "
            f"errors={len(self.errors)} warnings={len(self.warnings)}"
        )


__all__ = [
    "SourceType",
    "EventState",
    "Edition",
    "SourceConfig",
    "NewsItem",
    "EventItem",
    "HistoryItem",
    "DailySignalPayload",
    "ProvenanceManifest",
    "ValidationResult",
]
