"""
generate_perspective.py — weekly "Signal Perspective" thought-leadership column.

Pipeline position: runs on its own weekly workflow (Sunday). It does NOT
collect anything new. Instead it:

  1. loads the last 7 days of committed run payloads
     (data/runs/YYYY-MM-DD/daily_signal_payload.json);
  2. aggregates the week's validated stories and tag frequencies to find the
     dominant theme (deterministic — pure counting);
  3. re-validates the source links of the stories it will cite and drops any
     that have gone dark;
  4. calls the AI provider ONLY for essay language (framing, analysis,
     guidance), grounded strictly in the week's material, with a fully
     deterministic fallback;
  5. renders templates/weekly_perspective.md.j2 into a Jekyll post;
  6. writes _posts/YYYY-MM-DD-signal-perspective.md, perspective_payload.json,
     and perspective_provenance.json for the audit trail.

If fewer than MIN_CITATIONS stories survive link re-validation, no post is
written and the script exits non-zero so the workflow stops before publish.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

import summarize_with_ai as ai
from utils import (
    NY_TZ,
    POSTS_DIR,
    RUNS_DIR,
    TEMPLATES_DIR,
    display_date,
    get_logger,
    ny_now,
    ny_today,
    read_json,
    run_dir,
    truncate,
    validate_urls,
    write_json,
)

LOG = get_logger("generate_perspective")

LOOKBACK_DAYS = 7
MIN_CITATIONS = 2       # publish gate: need at least this many live cited stories
MAX_CITATIONS = 6
AUTHOR = "Aniket Abhishek Soni"
DISCLAIMER = (
    "This weekly perspective is AI-assisted and grounded exclusively in the week's "
    "source-reviewed Daily Tech Signal briefs."
)
MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _liquid_safe(text: Optional[str]) -> str:
    """Neutralize any Liquid delimiters so Jekyll won't try to parse them."""
    if not text:
        return ""
    return (
        text.replace("{{", "{ {").replace("}}", "} }")
        .replace("{%", "{ %").replace("%}", "% }")
    )


def _front_matter_date(post_date: date) -> str:
    dt = datetime(post_date.year, post_date.month, post_date.day, 10, 0, 0, tzinfo=NY_TZ)
    return dt.strftime("%Y-%m-%d %H:%M:%S %z")


def _week_range_label(start: date, end: date) -> str:
    if start.month == end.month:
        return f"{MONTHS[start.month - 1]} {start.day}–{end.day}, {end.year}"
    return (
        f"{MONTHS[start.month - 1]} {start.day} – "
        f"{MONTHS[end.month - 1]} {end.day}, {end.year}"
    )


# ──────────────────────────────────────────────────────────────────────
#  Load the week's committed payloads
# ──────────────────────────────────────────────────────────────────────
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
                    "date": d,
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


# ──────────────────────────────────────────────────────────────────────
#  Deterministic theme selection (pure counting — no AI)
# ──────────────────────────────────────────────────────────────────────
def _pick_theme(stories: list[dict]) -> tuple[str, list[str], Counter]:
    # Tags that merely name an aggregator/source are not themes.
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
    # De-duplicate by URL, keep order.
    seen: set = set()
    ordered = []
    for s in on_theme + rest:
        if s["url"] not in seen:
            seen.add(s["url"])
            ordered.append(s)
    return ordered


# ──────────────────────────────────────────────────────────────────────
#  AI language layer (essay only — every fact from the week's payloads)
# ──────────────────────────────────────────────────────────────────────
_ESSAY_SYSTEM = (
    "You are a senior data engineer, published researcher, and IEEE Senior Member "
    "writing a weekly thought-leadership column. Professional, direct, first-person. "
    "Use ONLY the headlines, themes, and summaries provided — invent no facts, "
    "numbers, names, products, or URLs. No marketing tone, no hype words."
)


def _ai_section(provider, prompt: str, min_len: int, fallback: str, limit: int = 1600) -> tuple[str, bool]:
    """Return (text, used_fallback)."""
    if provider is None:
        return fallback, True
    raw = provider.complete(_ESSAY_SYSTEM, prompt)
    text = ai._strip_model_urls((raw or "").strip())
    if not text or len(text) < min_len:
        return fallback, True
    return truncate(text, limit), False


def _material_block(theme: str, related: list[str], cited: list[dict]) -> str:
    lines = [f"DOMINANT THEME OF THE WEEK: {theme}"]
    if related:
        lines.append(f"RELATED THEMES: {', '.join(related)}")
    lines.append("THE WEEK'S VALIDATED STORIES:")
    for s in cited:
        lines.append(f"- [{s['source_name']}] {truncate(s['title'], 120)}")
        if s["summary"]:
            lines.append(f"  Summary: {truncate(s['summary'], 260)}")
    return "\n".join(lines)


def _fallback_opening(theme: str, n_stories: int, n_days: int, related: list[str]) -> str:
    rel = f", alongside {', '.join(related[:3])}" if related else ""
    briefs = "daily brief" if n_days == 1 else f"{n_days} daily briefs"
    return (
        f"Across th{'is' if n_days == 1 else 'e past'} week's {briefs}, "
        f"one theme kept resurfacing: **{theme}**{rel}. "
        f"This column steps back from the day-to-day feed — {n_stories} source-reviewed stories "
        f"this week — to ask what the pattern actually means for the people who build and run "
        f"data and AI systems."
    )


def _fallback_analysis(theme: str, cited: list[dict]) -> str:
    lead = cited[0] if cited else None
    parts = [
        f"The volume of validated signals around {theme} this week is itself the story. "
        "When a theme repeats across independent, source-reviewed items, it usually marks "
        "a capability that is moving from announcement to adoption — and that transition, "
        "not the launch, is where engineering organizations feel the impact."
    ]
    if lead:
        parts.append(
            f"The strongest signal of the week — “{_liquid_safe(lead['title'])}” "
            f"({lead['source_name']}) — is the anchor for that read."
        )
    parts.append(
        "My working rule for weeks like this: separate what changes an interface "
        "(APIs, formats, contracts) from what changes an economic assumption "
        "(cost per unit of compute, storage, or human review). Interface changes demand "
        "migration plans; economic changes demand architecture reviews. The week's items "
        "below contain both kinds."
    )
    return "\n\n".join(parts)


def _fallback_guidance(theme: str) -> str:
    return (
        f"Treat {theme} the way you would any production dependency: pin what you rely on, "
        "measure before and after, and keep an exit path. Concretely — pick one workload this "
        "week, write down the assumption the new development would change, and run the smallest "
        "experiment that could falsify it. Boring, observable systems remain the best position "
        "from which to adopt anything fast."
    )


# ──────────────────────────────────────────────────────────────────────
#  Main
# ──────────────────────────────────────────────────────────────────────
def main() -> int:
    today = ny_today()
    week_start = today - timedelta(days=LOOKBACK_DAYS - 1)
    rundir = run_dir(today)
    LOG.info("Generating Signal Perspective for week of %s", today.isoformat())

    stories, run_dates = _load_week(today)
    LOG.info("Loaded %d stories from %d daily runs", len(stories), len(run_dates))
    if not stories:
        LOG.error("No committed daily payloads found in the lookback window — nothing to write.")
        return 1

    theme, related, counts = _pick_theme(stories)
    ordered = _theme_stories(stories, theme)

    # ── Re-validate the links we intend to cite; drop dead ones ──
    candidates = ordered[: MAX_CITATIONS * 2]
    status = validate_urls([s["url"] for s in candidates])
    cited = [s for s in candidates if status.get(s["url"], False)][:MAX_CITATIONS]
    LOG.info("Citations: %d live of %d candidates", len(cited), len(candidates))
    if len(cited) < MIN_CITATIONS:
        LOG.error(
            "Only %d live citation(s) (< %d) — refusing to publish a weakly-sourced column.",
            len(cited), MIN_CITATIONS,
        )
        return 1

    # ── AI language (deterministic fallbacks throughout) ──
    provider = ai.get_provider()
    material = _material_block(theme, related, cited)
    fallbacks_used = []

    opening, fb = _ai_section(
        provider,
        material + "\n\nWrite the opening (2-4 sentences) of this week's column: name the "
        "dominant theme and why this week made it impossible to ignore. First person.",
        min_len=60,
        fallback=_fallback_opening(theme, len(stories), len(run_dates), related),
        limit=800,
    )
    fallbacks_used.append(fb)

    analysis, fb = _ai_section(
        provider,
        material + "\n\nWrite the core analysis (3-5 paragraphs): what the week's pattern "
        "around the dominant theme means for data engineering and AI practitioners. "
        "Argue a clear position. Reference the stories only by their given titles/sources.",
        min_len=200,
        fallback=_fallback_analysis(theme, cited),
        limit=3000,
    )
    fallbacks_used.append(fb)

    guidance, fb = _ai_section(
        provider,
        material + "\n\nWrite 'What I'd do about it' (1-2 paragraphs): concrete, practical "
        "guidance for engineering teams for the coming week. No invented specifics.",
        min_len=80,
        fallback=_fallback_guidance(theme),
        limit=1200,
    )
    fallbacks_used.append(fb)

    provider_name, model_name, provider_fb = ai.provider_info(provider)
    fallback_used = provider_fb or any(fallbacks_used)

    # ── Deterministic "week in numbers" ──
    sources = sorted({s["source_name"] for s in stories})
    top_counts = [{"tag": t, "count": c} for t, c in counts.most_common(6)]

    # ── Audit payload ──
    week_label = _week_range_label(week_start, today)
    title = f"Signal Perspective — {theme}: Week of {week_label}"
    tags = [theme] + related[:4] + ["Perspective"]
    payload: dict[str, Any] = {
        "post_date": today.isoformat(),
        "week_start": week_start.isoformat(),
        "week_label": week_label,
        "theme": theme,
        "related_themes": related,
        "tag_counts": top_counts,
        "stories_reviewed": len(stories),
        "runs_used": [d.isoformat() for d in run_dates],
        "citations": [
            {"title": s["title"], "url": s["url"], "source_name": s["source_name"]}
            for s in cited
        ],
        "title": title,
    }
    write_json(rundir / "perspective_payload.json", payload)

    # ── Template context (pre-formatted, Liquid-safe) ──
    context = {
        "title": _liquid_safe(title),
        "date_fm": _front_matter_date(today),
        "author": AUTHOR,
        "categories": ["Perspective", "AI", "Data Engineering"],
        "tags": tags,
        "description": (
            f"Weekly thought-leadership column: what this week's {theme} signals mean "
            "for data and AI engineering teams."
        ),
        "week_label": week_label,
        "theme": _liquid_safe(theme),
        "opening": _liquid_safe(opening),
        "analysis": _liquid_safe(analysis),
        "guidance": _liquid_safe(guidance),
        "stories_reviewed": len(stories),
        "runs_used": len(run_dates),
        "sources_count": len(sources),
        "tag_counts": [
            {"tag": _liquid_safe(tc["tag"]), "count": tc["count"]} for tc in top_counts
        ],
        "citations": [
            {
                "title": _liquid_safe(s["title"]),
                "url": s["url"],
                "source_name": _liquid_safe(s["source_name"]),
                "date": display_date(s["date"]),
            }
            for s in cited
        ],
        "disclaimer": DISCLAIMER,
    }

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(enabled_extensions=(), default=False),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    markdown = env.get_template("weekly_perspective.md.j2").render(**context)

    post_path = POSTS_DIR / f"{today.isoformat()}-signal-perspective.md"
    post_path.write_text(markdown, encoding="utf-8")
    LOG.info("Wrote post → %s (%d chars)", post_path, len(markdown))

    # ── Provenance ──
    write_json(
        rundir / "perspective_provenance.json",
        {
            "post_date": today.isoformat(),
            "generated_at": ny_now().isoformat(),
            "model_provider": provider_name,
            "model_name": model_name,
            "fallback_used": fallback_used,
            "stories_reviewed": len(stories),
            "runs_used": [d.isoformat() for d in run_dates],
            "citations": len(cited),
            "output_post_path": str(post_path.relative_to(POSTS_DIR.parent)),
            "validation_status": "generated",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
