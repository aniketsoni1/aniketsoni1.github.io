"""
validate_post.py — the final publish/no-publish gate.

Runs last. It re-reads the generated Markdown post and refuses to let the
workflow commit anything unsafe. Checks performed:

  * front matter exists and parses as YAML;
  * layout == post, title present, author == "Aniket Abhishek Soni", date present;
  * the AI-assisted disclaimer is present verbatim;
  * no placeholder text and no unresolved Liquid/Jekyll tags remain;
  * for a STANDARD edition, at least 3 linked news source URLs exist;
  * every URL is re-validated with async HEAD→GET; broken NEWS source links
    are treated as unsafe (fail), broken reference links (events/history) are
    warned about but tolerated (many event pages bot-block automated probes);
  * the output file path is valid.

Exit code 0 = safe to publish; non-zero = the workflow must not commit.
The provenance manifest's validation_status is updated in place.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

import yaml

from utils import get_logger, ny_today, read_json, run_dir, validate_urls, write_json, POSTS_DIR

LOG = get_logger("validate_post")

REQUIRED_AUTHOR = "Aniket Abhishek Soni"
DISCLAIMER = "This daily brief is AI-assisted and source-reviewed for public technology awareness."
MIN_LINKED_STORIES = 3

_PLACEHOLDER_RE = re.compile(r"\b(TODO|FIXME|PLACEHOLDER|LOREM IPSUM|TKTK|XXXX|REPLACE_ME|INSERT_)\b", re.I)
_LIQUID_LEFTOVER_RE = re.compile(r"\{\{|\}\}|\{%|%\}")
_SOURCE_LINK_RE = re.compile(r"Source:\s*\[[^\]]+\]\((https?://[^)]+)\)")
_ANY_LINK_RE = re.compile(r"\[[^\]]+\]\((https?://[^)]+)\)")
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


class Gate:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)
        LOG.error(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        LOG.warning(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


def _find_post(today) -> Optional[Path]:
    path = POSTS_DIR / f"{today.isoformat()}-daily-tech-signal.md"
    return path if path.exists() else None


def main() -> int:
    today = ny_today()
    gate = Gate()

    post_path = _find_post(today)
    if not post_path:
        LOG.error("No post found for %s at _posts/%s-daily-tech-signal.md", today, today.isoformat())
        return 1

    text = post_path.read_text(encoding="utf-8")

    # ── Front matter ──
    fm_match = _FRONT_MATTER_RE.match(text)
    front: dict = {}
    if not fm_match:
        gate.err("front matter block not found")
    else:
        try:
            front = yaml.safe_load(fm_match.group(1)) or {}
        except Exception as exc:
            gate.err(f"front matter is not valid YAML: {exc}")

    edition = str(front.get("edition", "standard"))
    is_short = edition == "short_signal" or "Short Signal edition" in text

    if front:
        if str(front.get("layout")) != "post":
            gate.err(f"layout must be 'post', got {front.get('layout')!r}")
        if not str(front.get("title", "")).strip():
            gate.err("title missing in front matter")
        elif "The Daily Tech Signal" not in str(front.get("title")):
            gate.warn("title does not contain the expected brand string")
        if str(front.get("author", "")).strip() != REQUIRED_AUTHOR:
            gate.err(f"author must be {REQUIRED_AUTHOR!r}, got {front.get('author')!r}")
        if not str(front.get("date", "")).strip():
            gate.err("date missing in front matter")
        elif not re.match(r"^\d{4}-\d{2}-\d{2}", str(front.get("date"))):
            gate.err(f"date not in YYYY-MM-DD form: {front.get('date')!r}")
        if not front.get("categories"):
            gate.warn("categories missing in front matter")

    body = text[fm_match.end():] if fm_match else text

    # ── Content integrity ──
    if DISCLAIMER not in body:
        gate.err("AI-assisted disclaimer is missing")
    if _PLACEHOLDER_RE.search(body):
        gate.err(f"placeholder text detected: {_PLACEHOLDER_RE.search(body).group(0)!r}")
    if _LIQUID_LEFTOVER_RE.search(body):
        gate.err("unresolved Liquid/Jekyll tags found in body")
    if "## Event Radar" not in body:
        gate.warn("Event Radar section missing")
    if "## This Day in Computing History" not in body:
        gate.warn("Computing History section missing")

    # ── Linked story count ──
    source_links = _SOURCE_LINK_RE.findall(body)
    if not is_short and len(source_links) < MIN_LINKED_STORIES:
        gate.err(
            f"standard edition requires >= {MIN_LINKED_STORIES} linked news stories, "
            f"found {len(source_links)}"
        )
    elif is_short:
        LOG.info("Short Signal edition — story-count minimum waived")

    # ── Link re-validation (async HEAD → GET) ──
    all_links = _ANY_LINK_RE.findall(body)
    status = validate_urls(all_links) if all_links else {}
    source_set = set(source_links)
    broken_news = [u for u in source_links if not status.get(u, False)]
    broken_ref = [u for u, ok in status.items() if not ok and u not in source_set]
    links_ok = sum(1 for v in status.values() if v)
    links_failed = sum(1 for v in status.values() if not v)

    if broken_news:
        gate.err(f"{len(broken_news)} broken NEWS source link(s): {broken_news[:3]}")
    for u in broken_ref:
        gate.warn(f"reference link unreachable (tolerated): {u}")

    valid_news_links = len(source_links) - len(broken_news)
    if not is_short and valid_news_links < MIN_LINKED_STORIES:
        gate.err(f"only {valid_news_links} news links pass revalidation (need {MIN_LINKED_STORIES})")

    # ── Update provenance ──
    rundir = run_dir(today, create=False)
    prov_path = rundir / "provenance.json"
    status_str = "failed" if not gate.ok else ("short_signal" if is_short else "passed")
    if prov_path.exists():
        try:
            prov = read_json(prov_path)
            prov["validation_status"] = status_str
            prov["links_validated"] = links_ok
            prov["links_failed"] = links_failed
            prov.setdefault("notes", []).append(
                f"validate_post: {status_str}; broken_news={len(broken_news)} broken_ref={len(broken_ref)}"
            )
            write_json(prov_path, prov)
        except Exception as exc:
            gate.warn(f"could not update provenance: {exc}")

    # ── Verdict ──
    LOG.info("Links: %d ok / %d failed | news links: %d valid", links_ok, links_failed, valid_news_links)
    if gate.warnings:
        LOG.info("%d warning(s)", len(gate.warnings))
    if not gate.ok:
        LOG.error("POST REJECTED (%d error(s)) — workflow must not commit", len(gate.errors))
        for e in gate.errors:
            print(f"  ✗ {e}", file=sys.stderr)
        return 1

    LOG.info("POST APPROVED (%s) → %s", status_str, post_path.name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
