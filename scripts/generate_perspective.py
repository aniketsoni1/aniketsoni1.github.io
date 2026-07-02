"""
generate_perspective.py — GOLD layer of the weekly Signal Perspective
pipeline: deterministic rendering + AI language.

Pipeline position: runs after aggregate_week.py (bronze) and
validate_week_payload.py (silver). It does NOT aggregate or select anything;
it consumes data/runs/YYYY-MM-DD/perspective_week_payload.json and:

  1. calls the AI provider ONLY for essay language (opening, analysis,
     guidance), grounded strictly in the aggregated material, with a fully
     deterministic fallback for every section;
  2. renders templates/weekly_perspective.md.j2 into a Jekyll post;
  3. writes _posts/YYYY-MM-DD-signal-perspective.md and
     perspective_provenance.json for the audit trail.

validate_perspective.py is the final publish gate after this script.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

import summarize_with_ai as ai
from utils import (
    NY_TZ,
    POSTS_DIR,
    TEMPLATES_DIR,
    display_date,
    get_logger,
    ny_now,
    ny_today,
    read_json,
    run_dir,
    truncate,
    write_json,
)

LOG = get_logger("generate_perspective")

AUTHOR = "Aniket Abhishek Soni"
DISCLAIMER = (
    "This weekly perspective is AI-assisted and grounded exclusively in the week's "
    "source-reviewed Daily Tech Signal briefs."
)


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


# ──────────────────────────────────────────────────────────────────────
#  AI language layer (essay only — every fact from the bronze payload)
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
        if s.get("summary"):
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
    rundir = run_dir(today)

    payload_path = rundir / "perspective_week_payload.json"
    if not payload_path.exists():
        LOG.error("Bronze payload missing: %s — run aggregate_week.py first.", payload_path)
        return 1
    wk = read_json(payload_path)

    theme: str = wk["theme"]
    related: list[str] = wk.get("related_themes", [])
    cited: list[dict] = wk["citations"]
    week_label: str = wk["week_label"]
    LOG.info("Rendering Signal Perspective — theme=%r, %d citations", theme, len(cited))

    # ── AI language (deterministic fallbacks throughout) ──
    provider = ai.get_provider()
    material = _material_block(theme, related, cited)
    fallbacks_used = []

    opening, fb = _ai_section(
        provider,
        material + "\n\nWrite the opening (2-4 sentences) of this week's column: name the "
        "dominant theme and why this week made it impossible to ignore. First person.",
        min_len=60,
        fallback=_fallback_opening(theme, wk["stories_reviewed"], len(wk["runs_used"]), related),
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

    # ── Template context (pre-formatted, Liquid-safe) ──
    title = f"Signal Perspective — {theme}: Week of {week_label}"
    context = {
        "title": _liquid_safe(title),
        "date_fm": _front_matter_date(today),
        "author": AUTHOR,
        "categories": ["Perspective", "AI", "Data Engineering"],
        "tags": [theme] + related[:4] + ["Perspective"],
        "description": (
            f"Weekly thought-leadership column: what this week's {theme} signals mean "
            "for data and AI engineering teams."
        ),
        "week_label": week_label,
        "theme": _liquid_safe(theme),
        "opening": _liquid_safe(opening),
        "analysis": _liquid_safe(analysis),
        "guidance": _liquid_safe(guidance),
        "stories_reviewed": wk["stories_reviewed"],
        "runs_used": len(wk["runs_used"]),
        "sources_count": wk["sources_count"],
        "tag_counts": [
            {"tag": _liquid_safe(tc["tag"]), "count": tc["count"]}
            for tc in wk.get("tag_counts", [])
        ],
        "citations": [
            {
                "title": _liquid_safe(s["title"]),
                "url": s["url"],
                "source_name": _liquid_safe(s["source_name"]),
                "date": display_date(date.fromisoformat(s["date"])),
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
            "stories_reviewed": wk["stories_reviewed"],
            "runs_used": wk["runs_used"],
            "citations": len(cited),
            "output_post_path": str(post_path.relative_to(POSTS_DIR.parent)),
            "validation_status": "generated",
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
