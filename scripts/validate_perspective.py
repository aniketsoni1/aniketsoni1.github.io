"""
validate_perspective.py - publish/no-publish gate for the weekly column.

Mirrors validate_post.py, tuned to the Signal Perspective format:

  * front matter exists, parses, layout == post, author correct, date present,
    'Perspective' in categories, edition == perspective;
  * the weekly disclaimer is present verbatim;
  * no placeholder text and no unresolved Liquid/Jekyll tags;
  * at least MIN_CITATIONS citation links exist and re-validate live;
  * provenance manifest updated in place.

Exit code 0 = safe to publish; non-zero = the workflow must not commit.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

import yaml

from utils import POSTS_DIR, get_logger, ny_today, read_json, run_dir, validate_urls, write_json

LOG = get_logger("validate_perspective")

REQUIRED_AUTHOR = "Aniket Abhishek Soni"
DISCLAIMER = (
    "This weekly perspective is AI-assisted and grounded exclusively in the week's "
    "source-reviewed Daily Tech Signal briefs."
)
MIN_CITATIONS = 2

_PLACEHOLDER_RE = re.compile(r"\b(TODO|FIXME|PLACEHOLDER|LOREM IPSUM|TKTK|XXXX|REPLACE_ME|INSERT_)\b", re.I)
_LIQUID_LEFTOVER_RE = re.compile(r"\{\{|\}\}|\{%|%\}")
_ANY_LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^)]+)\)")
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def _find_post(today) -> Optional[Path]:
    path = POSTS_DIR / f"{today.isoformat()}-signal-perspective.md"
    return path if path.exists() else None


def main() -> int:
    today = ny_today()
    errors: list[str] = []
    warnings: list[str] = []

    post_path = _find_post(today)
    if not post_path:
        LOG.error("No perspective post found at _posts/%s-signal-perspective.md", today.isoformat())
        return 1

    text = post_path.read_text(encoding="utf-8")

    # ── Front matter ──
    fm_match = _FRONT_MATTER_RE.match(text)
    front: dict = {}
    if not fm_match:
        errors.append("front matter block not found")
    else:
        try:
            front = yaml.safe_load(fm_match.group(1)) or {}
        except Exception as exc:
            errors.append(f"front matter is not valid YAML: {exc}")

    if front:
        if str(front.get("layout")) != "post":
            errors.append(f"layout must be 'post', got {front.get('layout')!r}")
        if not str(front.get("title", "")).strip():
            errors.append("title missing in front matter")
        elif "Signal Perspective" not in str(front.get("title")):
            warnings.append("title does not contain 'Signal Perspective'")
        if str(front.get("author", "")).strip() != REQUIRED_AUTHOR:
            errors.append(f"author must be {REQUIRED_AUTHOR!r}, got {front.get('author')!r}")
        if not str(front.get("date", "")).strip():
            errors.append("date missing in front matter")
        cats = front.get("categories") or []
        if "Perspective" not in [str(c) for c in cats]:
            errors.append("'Perspective' missing from categories")
        if str(front.get("edition")) != "perspective":
            errors.append(f"edition must be 'perspective', got {front.get('edition')!r}")

    body = text[fm_match.end():] if fm_match else text

    # ── Content integrity ──
    if DISCLAIMER not in body:
        errors.append("weekly disclaimer is missing")
    if _PLACEHOLDER_RE.search(body):
        errors.append(f"placeholder text detected: {_PLACEHOLDER_RE.search(body).group(0)!r}")
    if _LIQUID_LEFTOVER_RE.search(body):
        errors.append("unresolved Liquid/Jekyll tags found in body")
    for section in ("## The Week in Numbers", "## The Signal", "## What I'd Do About It", "## Evidence From the Week"):
        if section not in body:
            errors.append(f"required section missing: {section!r}")

    # ── Citation link re-validation ──
    links = _ANY_LINK_RE.findall(body)
    status = validate_urls(links) if links else {}
    live = [u for u, ok in status.items() if ok]
    dead = [u for u, ok in status.items() if not ok]
    if len(live) < MIN_CITATIONS:
        errors.append(f"only {len(live)} live citation link(s) (need {MIN_CITATIONS})")
    for u in dead:
        warnings.append(f"link unreachable: {u}")

    # ── Update provenance ──
    prov_path = run_dir(today, create=False) / "perspective_provenance.json"
    status_str = "failed" if errors else "passed"
    if prov_path.exists():
        try:
            prov = read_json(prov_path)
            prov["validation_status"] = status_str
            prov.setdefault("notes", []).append(
                f"validate_perspective: {status_str}; live_links={len(live)} dead_links={len(dead)}"
            )
            write_json(prov_path, prov)
        except Exception as exc:
            warnings.append(f"could not update provenance: {exc}")

    for w in warnings:
        LOG.warning(w)
    if errors:
        LOG.error("PERSPECTIVE REJECTED (%d error(s)) - workflow must not commit", len(errors))
        for e in errors:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1

    LOG.info("PERSPECTIVE APPROVED → %s", post_path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
