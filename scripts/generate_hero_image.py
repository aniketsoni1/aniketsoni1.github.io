"""
generate_hero_image.py — optional AI hero image for the daily post.

Runs in the gold-generate job BEFORE generate_post.py. Provider cascade,
matching the repo's "never let one provider's failure kill the run" rule:

  1. Google `GEMINI_IMAGE_MODEL` (default: gemini-2.5-flash-image) via
     GEMINI_API_KEY.
     COST NOTE (verified against Google's pricing page, July 2026): this
     model's image output has NO free tier — it is billed per image at
     ~$0.039 / 1024px image. Small but REAL money (~$1.20/month at daily
     cadence), despite third-party blog posts claiming otherwise.
     LIFECYCLE NOTE: Google's deprecations table schedules
     gemini-2.5-flash-image for shutdown on 2026-10-02 (suggested
     replacement: gemini-3.1-flash-image-preview). The model name therefore
     lives in the GEMINI_IMAGE_MODEL env var — swapping is a one-line
     workflow change, no code edit.
  2. Hugging Face serverless Inference (black-forest-labs/FLUX.1-schnell)
     via HUGGINGFACE_API_KEY. Chosen for its Apache-2.0 license (safe for
     reuse on a public blog) and speed.
  3. Skip the image entirely — a missing hero must NEVER fail the job.

Every outcome (which provider served, or that both were skipped) is logged
and recorded in data/runs/YYYY-MM-DD/hero_image.json so the Action log and
audit trail show the path taken. generate_post.py reads that manifest and
adds the image to the post's front matter when present.

Style: abstract tech-minimal — geometric, circuit-inspired artwork in the
site's palette (near-black + teal). Deliberately NOT a literal illustration
of any story: abstract art can't misrepresent the news.

Exit code is ALWAYS 0.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Optional

from utils import REPO_ROOT, get_logger, ny_today, read_json, run_dir, write_json

LOG = get_logger("hero_image")

HERO_DIR = REPO_ROOT / "assets" / "img" / "signal"
DEFAULT_GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"
HF_MODEL = "black-forest-labs/FLUX.1-schnell"
# HF's current serverless endpoint (the old api-inference.huggingface.co
# host still aliases here; router is the documented form since 2025).
HF_URL = f"https://router.huggingface.co/hf-inference/models/{HF_MODEL}"
TIMEOUT = 90

_MAGIC = {b"\x89PNG": ".png", b"\xff\xd8\xff": ".jpg", b"RIFF": ".webp"}


def _ext_for(data: bytes) -> str:
    for magic, ext in _MAGIC.items():
        if data[: len(magic)] == magic:
            return ext
    return ".png"


def _build_prompt() -> str:
    """Abstract-minimal prompt seeded by the day's validated themes."""
    themes = []
    try:
        payload = read_json(run_dir(ny_today(), create=False) / "news_validated.json")
        seen = set()
        for item in payload.get("items", []):
            for t in item.get("tags", []):
                if t and t.lower() not in seen:
                    seen.add(t.lower())
                    themes.append(t)
    except Exception:
        pass
    theme_str = ", ".join(themes[:5]) or "data engineering and artificial intelligence"
    return (
        "Abstract minimal digital artwork, dark near-black background (#050505) with "
        f"luminous teal (#009e9e) accents, geometric circuit-board lines and nodes evoking {theme_str}, "
        "subtle grid, clean negative space, flat vector style, wide 16:9 composition. "
        "No text, no letters, no numbers, no logos, no people, no faces."
    )


def _try_gemini(prompt: str) -> tuple[Optional[bytes], str]:
    """Returns (image_bytes|None, reason). Reason lands in the audit manifest."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        LOG.info("Gemini: no GEMINI_API_KEY — skipping")
        return None, "skipped: GEMINI_API_KEY not set"
    model = os.environ.get("GEMINI_IMAGE_MODEL", "").strip() or DEFAULT_GEMINI_IMAGE_MODEL
    import requests

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    try:
        resp = requests.post(
            url,
            params={"key": api_key},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
            },
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            reason = f"HTTP {resp.status_code}: {resp.text[:300]}"
            LOG.warning("Gemini [%s] %s", model, reason)
            return None, reason
        data = resp.json()
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data") or {}
                if inline.get("data"):
                    LOG.info("Gemini [%s] served the hero image", model)
                    return base64.b64decode(inline["data"]), "ok"
        # Empty / content-policy-blocked / text-only response — all fall through.
        reason = f"no image part in response (finishReason={ (data.get('candidates') or [{}])[0].get('finishReason') })"
        LOG.warning("Gemini [%s] %s", model, reason)
        return None, reason
    except Exception as exc:
        LOG.warning("Gemini [%s] failed: %s", model, exc)
        return None, f"exception: {exc}"


def _try_flux(prompt: str) -> tuple[Optional[bytes], str]:
    """Returns (image_bytes|None, reason). Reason lands in the audit manifest."""
    token = os.environ.get("HUGGINGFACE_API_KEY", "").strip()
    if not token:
        LOG.info("FLUX: no HUGGINGFACE_API_KEY — skipping")
        return None, "skipped: HUGGINGFACE_API_KEY not set"
    import requests

    try:
        resp = requests.post(
            HF_URL,
            headers={"Authorization": f"Bearer {token}"},
            json={"inputs": prompt},
            timeout=TIMEOUT,
        )
        ctype = resp.headers.get("content-type", "")
        if resp.status_code == 200 and ctype.startswith("image/"):
            LOG.info("FLUX.1-schnell served the hero image")
            return resp.content, "ok"
        reason = f"HTTP {resp.status_code} ({ctype}): {resp.text[:300]}"
        LOG.warning("FLUX %s", reason)
        return None, reason
    except Exception as exc:
        LOG.warning("FLUX failed: %s", exc)
        return None, f"exception: {exc}"


def main() -> int:
    today = ny_today()
    rundir = run_dir(today)
    prompt = _build_prompt()
    LOG.info("Hero prompt: %s", prompt[:140])

    provider, model, image = None, None, None
    attempts: list[dict] = []

    gemini_model = os.environ.get("GEMINI_IMAGE_MODEL", "").strip() or DEFAULT_GEMINI_IMAGE_MODEL
    image, reason = _try_gemini(prompt)
    attempts.append({"provider": "gemini", "model": gemini_model, "ok": image is not None, "reason": reason})
    if image is not None:
        provider, model = "gemini", gemini_model
    else:
        image, reason = _try_flux(prompt)
        attempts.append({"provider": "huggingface", "model": HF_MODEL, "ok": image is not None, "reason": reason})
        if image is not None:
            provider, model = "huggingface", HF_MODEL

    manifest: dict = {
        "post_date": today.isoformat(),
        "provider": provider,
        "model": model,
        "attempts": attempts,  # audit: exactly why each leg served or didn't
        "prompt": prompt,
        "path": None,
        "alt": "Abstract teal-on-dark circuit artwork for today's Daily Tech Signal",
    }

    if image is None:
        LOG.warning("No hero image today (both providers skipped/failed) — post ships without one.")
    else:
        HERO_DIR.mkdir(parents=True, exist_ok=True)
        ext = _ext_for(image)
        path = HERO_DIR / f"{today.isoformat()}-hero{ext}"
        path.write_bytes(image)
        manifest["path"] = f"/assets/img/signal/{path.name}"
        LOG.info("Hero image (%d KB, %s) → %s", len(image) // 1024, provider, path)

    write_json(rundir / "hero_image.json", manifest)

    # Surface the outcome on the Actions run summary page (no log digging).
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            lines = ["### 🎨 Hero image", ""]
            for a in attempts:
                icon = "✅" if a["ok"] else "▫️"
                lines.append(f"- {icon} `{a['provider']}` ({a['model']}): {a['reason']}")
            if manifest["path"]:
                lines.append(f"\n**Served:** `{manifest['path']}`")
            else:
                lines.append("\n**No image this run** — post ships without one (by design).")
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        except Exception:
            pass

    return 0  # by design: a missing image never fails the pipeline


if __name__ == "__main__":
    raise SystemExit(main())
