"""
utils.py - shared plumbing for the Daily Tech Signal pipeline.

Everything that more than one stage needs lives here: repo-relative paths,
America/New_York date handling, the per-run directory layout, JSON/YAML I/O
that understands Pydantic models, HTML cleaning, slugging, and a polite,
cached feed/HTTP fetcher with retries.

Nothing here talks to an AI provider - that is isolated in
summarize_with_ai.py so the rest of the pipeline stays deterministic.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml

# Timezone: prefer stdlib zoneinfo (Python 3.9+). tzdata is pinned in
# requirements.txt so this also works on minimal/Windows runners.
try:
    from zoneinfo import ZoneInfo

    NY_TZ = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - extremely defensive
    NY_TZ = timezone.utc

# Optional dependency - used for robust HTML stripping when present.
try:
    from bs4 import BeautifulSoup  # type: ignore

    _HAVE_BS4 = True
except Exception:  # pragma: no cover
    _HAVE_BS4 = False


# ──────────────────────────────────────────────────────────────────────
#  Paths
# ──────────────────────────────────────────────────────────────────────
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
DATA_DIR: Path = REPO_ROOT / "data"
RUNS_DIR: Path = DATA_DIR / "runs"
CACHE_DIR: Path = DATA_DIR / "cache"
POSTS_DIR: Path = REPO_ROOT / "_posts"
TEMPLATES_DIR: Path = REPO_ROOT / "templates"

for _d in (RUNS_DIR, CACHE_DIR, POSTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────────────────────────────
#  Logging
# ──────────────────────────────────────────────────────────────────────
def get_logger(name: str) -> logging.Logger:
    """Return a configured logger that writes concise, level-tagged lines."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                              datefmt="%H:%M:%S")
        )
        logger.addHandler(handler)
        logger.setLevel(os.environ.get("SIGNAL_LOG_LEVEL", "INFO").upper())
        logger.propagate = False
    return logger


LOG = get_logger("utils")


# ──────────────────────────────────────────────────────────────────────
#  Dates
# ──────────────────────────────────────────────────────────────────────
def ny_now() -> datetime:
    """Current time in America/New_York."""
    return datetime.now(tz=NY_TZ)


def ny_today() -> date:
    """
    'Today' in America/New_York.

    Override with SIGNAL_DATE=YYYY-MM-DD for deterministic local testing /
    backfills (the whole pipeline keys off this single function).
    """
    override = os.environ.get("SIGNAL_DATE", "").strip()
    if override:
        return datetime.strptime(override, "%Y-%m-%d").date()
    return ny_now().date()


def display_date(d: date) -> str:
    """'June 30, 2026' - no zero-padded day."""
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────────────
#  Run directory
# ──────────────────────────────────────────────────────────────────────
def run_dir(d: Optional[date] = None, create: bool = True) -> Path:
    """Return data/runs/YYYY-MM-DD/ for the given date (default: NY today)."""
    d = d or ny_today()
    path = RUNS_DIR / d.isoformat()
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


# ──────────────────────────────────────────────────────────────────────
#  YAML / JSON I/O
# ──────────────────────────────────────────────────────────────────────
def load_yaml(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _to_jsonable(obj: Any) -> Any:
    """Coerce Pydantic models, dates, and containers to JSON-safe values."""
    # Pydantic v2 model?
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    return obj


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(_to_jsonable(obj), fh, ensure_ascii=False, indent=2)
    LOG.debug("wrote %s", path)


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ──────────────────────────────────────────────────────────────────────
#  Text helpers
# ──────────────────────────────────────────────────────────────────────
_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")


def clean_html(text: Optional[str]) -> str:
    """Strip tags/entities and collapse whitespace from feed HTML."""
    if not text:
        return ""
    if _HAVE_BS4:
        try:
            text = BeautifulSoup(text, "html.parser").get_text(" ")
        except Exception:
            text = _TAG_RE.sub(" ", text)
    else:
        text = _TAG_RE.sub(" ", text)
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
        .replace("&nbsp;", " ")
    )
    return _WS_RE.sub(" ", text).strip()


def truncate(text: str, limit: int = 320) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(".,;:") + "…"


# House style: no em dashes anywhere in published output. AI providers love
# them, so this is enforced at the render boundary (see generate_post.py /
# generate_perspective.py) regardless of what a model returns. Codepoints are
# spelled with escapes so a bulk find/replace of literal dashes never alters
# this function. U+2014 em dash and U+2015 horizontal bar -> hyphen; spacing is
# preserved (" - " becomes " - "). En dash (U+2013) is intentionally left
# alone so numeric ranges keep reading naturally.
_EMDASH_RE = re.compile("[\u2014\u2015]")


def normalize_dashes(text: str) -> str:
    """Replace em dashes / horizontal bars with a plain hyphen."""
    if not text:
        return text
    return _EMDASH_RE.sub("-", text)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    text = (text or "").lower().strip()
    text = _SLUG_RE.sub("-", text)
    return text.strip("-")


# A small stopword-free keyword map for deterministic tag extraction.
_TAG_KEYWORDS = {
    "ai": "AI",
    "artificial intelligence": "AI",
    "machine learning": "Machine Learning",
    "llm": "LLMs",
    "large language model": "LLMs",
    "genai": "GenAI",
    "generative": "GenAI",
    "agent": "AI Agents",
    "data engineering": "Data Engineering",
    "pipeline": "Data Pipelines",
    "etl": "ETL",
    "lakehouse": "Lakehouse",
    "spark": "Apache Spark",
    "databricks": "Databricks",
    "snowflake": "Snowflake",
    "kafka": "Streaming",
    "streaming": "Streaming",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "docker": "Containers",
    "cloud": "Cloud",
    "aws": "AWS",
    "azure": "Azure",
    "gcp": "Google Cloud",
    "google cloud": "Google Cloud",
    "nvidia": "GPUs",
    "gpu": "GPUs",
    "open source": "Open Source",
    "open-source": "Open Source",
    "security": "Security",
    "vulnerabilit": "Security",
    "database": "Databases",
    "postgres": "Databases",
    "vector": "Vector Databases",
    "mlops": "MLOps",
    "governance": "Data Governance",
    "python": "Python",
    "github": "Developer Tools",
    "api": "APIs",
    "model": "AI Models",
    "research": "Research",
    "arxiv": "Research",
}


def extract_tags(text: str, extra: Optional[Iterable[str]] = None, limit: int = 8) -> list[str]:
    """Deterministically derive display tags from text + optional seeds."""
    haystack = (text or "").lower()
    found: list[str] = []
    for needle, label in _TAG_KEYWORDS.items():
        if needle in haystack and label not in found:
            found.append(label)
    if extra:
        for e in extra:
            label = e.strip()
            if label and label not in found:
                found.append(label)
    return found[:limit]


# ──────────────────────────────────────────────────────────────────────
#  HTTP / feed fetching (requests + on-disk conditional-GET cache)
# ──────────────────────────────────────────────────────────────────────
DEFAULT_UA = "DailyTechSignal/1.0 (+https://aniketsoni.com)"


def _cache_paths(url: str) -> tuple[Path, Path]:
    key = slugify(url)[:120] or "feed"
    return CACHE_DIR / f"{key}.body", CACHE_DIR / f"{key}.meta.json"


def fetch_url(
    url: str,
    timeout: int = 20,
    user_agent: str = DEFAULT_UA,
    use_cache: bool = True,
    retries: int = 2,
) -> Optional[bytes]:
    """
    GET a URL with a conditional-GET cache (ETag / Last-Modified) and simple
    retry. Returns raw bytes, or None on failure. Never raises - a dead feed
    must not crash the run.
    """
    import requests  # local import keeps module import cheap

    body_path, meta_path = _cache_paths(url)
    headers = {"User-Agent": user_agent, "Accept": "*/*"}

    if use_cache and meta_path.exists() and body_path.exists():
        try:
            meta = read_json(meta_path)
            if meta.get("etag"):
                headers["If-None-Match"] = meta["etag"]
            if meta.get("last_modified"):
                headers["If-Modified-Since"] = meta["last_modified"]
        except Exception:
            pass

    last_err: Optional[str] = None
    for attempt in range(1, retries + 2):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 304 and body_path.exists():
                LOG.debug("cache hit (304) %s", url)
                return body_path.read_bytes()
            resp.raise_for_status()
            content = resp.content
            if use_cache:
                try:
                    body_path.write_bytes(content)
                    write_json(
                        meta_path,
                        {
                            "etag": resp.headers.get("ETag"),
                            "last_modified": resp.headers.get("Last-Modified"),
                            "fetched_at": iso_now(),
                            "url": url,
                        },
                    )
                except Exception as exc:  # cache write is best-effort
                    LOG.debug("cache write failed for %s: %s", url, exc)
            return content
        except Exception as exc:
            last_err = str(exc)
            LOG.debug("fetch attempt %d failed for %s: %s", attempt, url, exc)

    LOG.warning("giving up on %s (%s)", url, last_err)
    # Fall back to any stale cached body rather than nothing.
    if use_cache and body_path.exists():
        LOG.info("serving stale cache for %s", url)
        return body_path.read_bytes()
    return None


def env_flag(name: str) -> bool:
    """True when an env var is present and non-empty (secret detection)."""
    return bool(os.environ.get(name, "").strip())


# ──────────────────────────────────────────────────────────────────────
#  Async link validation (HEAD → GET fallback), bot-block tolerant
# ──────────────────────────────────────────────────────────────────────
# Statuses that mean "the resource exists but the server is refusing our
# automated probe" - we treat these as reachable rather than broken so we
# don't drop legitimate links behind bot protection (LinkedIn, some CDNs).
_SOFT_OK_STATUS = {401, 403, 405, 406, 429, 503, 999}


def _status_is_ok(code: int) -> Optional[bool]:
    """True=ok, False=broken, None=ambiguous (retry with GET)."""
    if code < 400 or code in _SOFT_OK_STATUS:
        return True
    if code in (400, 404, 405, 410, 501):
        return None if code in (400, 405, 501) else False
    return False


def _validate_urls_async(unique: list[str], timeout: int, concurrency: int, user_agent: str) -> dict[str, bool]:
    """Primary path: async HEAD→GET with httpx. Raises on env/import problems."""
    import asyncio

    import httpx

    async def _check_one(client, sem, url: str) -> tuple[str, bool]:
        async with sem:
            for method in ("HEAD", "GET"):
                try:
                    headers = {"User-Agent": user_agent}
                    if method == "GET":
                        headers["Range"] = "bytes=0-2048"
                    resp = await client.request(method, url, follow_redirects=True, headers=headers)
                    verdict = _status_is_ok(resp.status_code)
                    if verdict is None and method == "HEAD":
                        continue  # ambiguous → try GET
                    return url, bool(verdict)
                except Exception:
                    if method == "GET":
                        return url, False
                    continue
            return url, False

    async def _run() -> dict[str, bool]:
        sem = asyncio.Semaphore(concurrency)
        # trust_env=False avoids inheriting exotic proxies (e.g. SOCKS) that
        # would otherwise require optional extras; feeds/links are public.
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            results = await asyncio.gather(*(_check_one(client, sem, u) for u in unique))
        return dict(results)

    try:
        return asyncio.run(_run())
    except RuntimeError:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(lambda: asyncio.run(_run())).result()


def _validate_urls_sync(unique: list[str], timeout: int, concurrency: int, user_agent: str) -> dict[str, bool]:
    """Fallback path: synchronous requests HEAD→GET across a thread pool."""
    import concurrent.futures

    import requests

    def _one(url: str) -> tuple[str, bool]:
        for method in ("head", "get"):
            try:
                fn = getattr(requests, method)
                kwargs = {"timeout": timeout, "allow_redirects": True,
                          "headers": {"User-Agent": user_agent}}
                if method == "get":
                    kwargs["stream"] = True
                resp = fn(url, **kwargs)
                verdict = _status_is_ok(resp.status_code)
                if verdict is None and method == "head":
                    continue
                return url, bool(verdict)
            except Exception:
                if method == "get":
                    return url, False
                continue
        return url, False

    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
        return dict(ex.map(_one, unique))


def validate_urls(
    urls: list[str],
    timeout: int = 15,
    concurrency: int = 10,
    user_agent: str = DEFAULT_UA,
) -> dict[str, bool]:
    """
    Validate a list of URLs concurrently. Returns {url: is_ok}.

    Strategy per URL: HEAD first; on an unsupported method or ambiguous status,
    fall back to a ranged GET. 2xx/3xx = ok; soft-block statuses (403/429/…) =
    ok (present but bot-protected); 404/410/5xx/timeouts/DNS = broken.

    Robustness: the async httpx path is primary (honouring the spec); if the
    runtime can't run it (missing extras, exotic proxy), we transparently fall
    back to a synchronous requests pass. Never raises.

    Offline/local dev: set SIGNAL_SKIP_LINK_CHECK=1 to assume all links valid
    (prints a loud warning). NEVER set this in CI - it disables the safety gate.
    """
    unique = [u for u in dict.fromkeys(u for u in urls if u)]
    if not unique:
        return {}

    if os.environ.get("SIGNAL_SKIP_LINK_CHECK", "").strip():
        LOG.warning("SIGNAL_SKIP_LINK_CHECK set - assuming all %d links valid (OFFLINE MODE)", len(unique))
        return {u: True for u in unique}

    try:
        return _validate_urls_async(unique, timeout, concurrency, user_agent)
    except Exception as exc:
        LOG.warning("async link check unavailable (%s); using synchronous fallback", exc)
        try:
            return _validate_urls_sync(unique, timeout, concurrency, user_agent)
        except Exception as exc2:
            LOG.error("link validation failed entirely: %s", exc2)
            return {u: False for u in unique}


__all__ = [
    "REPO_ROOT",
    "DATA_DIR",
    "RUNS_DIR",
    "CACHE_DIR",
    "POSTS_DIR",
    "TEMPLATES_DIR",
    "NY_TZ",
    "get_logger",
    "ny_now",
    "ny_today",
    "display_date",
    "iso_now",
    "run_dir",
    "load_yaml",
    "write_json",
    "read_json",
    "clean_html",
    "truncate",
    "normalize_dashes",
    "slugify",
    "extract_tags",
    "fetch_url",
    "env_flag",
    "validate_urls",
]
