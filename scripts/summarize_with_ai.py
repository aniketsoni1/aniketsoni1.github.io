"""
summarize_with_ai.py - the ONLY module that talks to an AI model.

It exposes a small, provider-agnostic surface:

    provider = get_provider()                      # first available, or None
    summary, why = summarize_news_item(item, provider)
    intro       = write_intro(items, events, history, provider)
    takeaway    = write_takeaway(items, provider)

Provider priority (each used only if its secret(s) are present):
    1. Google Gemini        GEMINI_API_KEY
    2. Groq                 GROQ_API_KEY
    3. OpenRouter           OPENROUTER_API_KEY
    4. Cloudflare Workers AI CLOUDFLARE_ACCOUNT_ID + CLOUDFLARE_API_TOKEN
    5. Hugging Face          HUGGINGFACE_API_KEY
    6. deterministic, non-AI fallback (always available)

Every model default is overridable via a *_MODEL env var so provider model
churn never breaks the pipeline. All model output is passed through a
source-grounding guard: summaries may not introduce numbers/URLs absent from
the source text; anything that fails the guard is discarded in favour of the
deterministic summary. Nothing here can crash the run - failures degrade to
the fallback.
"""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from schemas import EventItem, HistoryItem, NewsItem
from utils import env_flag, get_logger, truncate

LOG = get_logger("summarize_ai")

_TEMP = float(os.environ.get("SIGNAL_AI_TEMPERATURE", "0.3"))
_MAXTOK = int(os.environ.get("SIGNAL_AI_MAX_TOKENS", "260"))
_TIMEOUT = int(os.environ.get("SIGNAL_AI_TIMEOUT", "40"))


# ══════════════════════════════════════════════════════════════════════
#  Provider interface
# ══════════════════════════════════════════════════════════════════════
class Provider(ABC):
    name: str = "base"

    @property
    @abstractmethod
    def model(self) -> str: ...

    @abstractmethod
    def available(self) -> bool: ...

    @abstractmethod
    def _raw_complete(self, system: str, prompt: str) -> str: ...

    def complete(self, system: str, prompt: str) -> Optional[str]:
        """Public entry with retry + total failure isolation."""
        try:
            text = self._retry_complete(system, prompt)
            return (text or "").strip() or None
        except Exception as exc:
            LOG.warning("[%s] completion failed: %s", self.name, exc)
            return None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8), reraise=True)
    def _retry_complete(self, system: str, prompt: str) -> str:
        return self._raw_complete(system, prompt)


def _post_json(url: str, headers: dict, payload: dict) -> dict:
    import requests

    resp = requests.post(url, headers=headers, json=payload, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _openai_chat(url: str, api_key: str, model: str, system: str, prompt: str, extra_headers: Optional[dict] = None) -> str:
    """Shared helper for OpenAI-compatible /chat/completions providers."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": _TEMP,
        "max_tokens": _MAXTOK,
    }
    data = _post_json(url, headers, payload)
    return data["choices"][0]["message"]["content"]


# ── 1. Google Gemini ──────────────────────────────────────────────────
class GeminiProvider(Provider):
    name = "gemini"

    @property
    def model(self) -> str:
        return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    def available(self) -> bool:
        return env_flag("GEMINI_API_KEY")

    def _raw_complete(self, system: str, prompt: str) -> str:
        key = os.environ["GEMINI_API_KEY"]
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={key}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": _TEMP, "maxOutputTokens": _MAXTOK},
        }
        data = _post_json(url, {"Content-Type": "application/json"}, payload)
        return data["candidates"][0]["content"]["parts"][0]["text"]


# ── 2. Groq (OpenAI-compatible) ───────────────────────────────────────
class GroqProvider(Provider):
    name = "groq"

    @property
    def model(self) -> str:
        # NOTE: Groq deprecated the older llama-3.x versatile/instant IDs in
        # mid-2026. Override with GROQ_MODEL to track console.groq.com/docs/models.
        return os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")

    def available(self) -> bool:
        return env_flag("GROQ_API_KEY")

    def _raw_complete(self, system: str, prompt: str) -> str:
        return _openai_chat(
            "https://api.groq.com/openai/v1/chat/completions",
            os.environ["GROQ_API_KEY"], self.model, system, prompt,
        )


# ── 3. OpenRouter (free models, OpenAI-compatible) ────────────────────
class OpenRouterProvider(Provider):
    name = "openrouter"

    @property
    def model(self) -> str:
        return os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")

    def available(self) -> bool:
        return env_flag("OPENROUTER_API_KEY")

    def _raw_complete(self, system: str, prompt: str) -> str:
        return _openai_chat(
            "https://openrouter.ai/api/v1/chat/completions",
            os.environ["OPENROUTER_API_KEY"], self.model, system, prompt,
            extra_headers={
                "HTTP-Referer": "https://aniketsoni.com",
                "X-Title": "The Daily Tech Signal",
            },
        )


# ── 4. Cloudflare Workers AI ──────────────────────────────────────────
class CloudflareProvider(Provider):
    name = "cloudflare"

    @property
    def model(self) -> str:
        return os.environ.get("CLOUDFLARE_MODEL", "@cf/meta/llama-3.1-8b-instruct")

    def available(self) -> bool:
        return env_flag("CLOUDFLARE_ACCOUNT_ID") and env_flag("CLOUDFLARE_API_TOKEN")

    def _raw_complete(self, system: str, prompt: str) -> str:
        account = os.environ["CLOUDFLARE_ACCOUNT_ID"]
        token = os.environ["CLOUDFLARE_API_TOKEN"]
        url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{self.model}"
        payload = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": _MAXTOK,
            "temperature": _TEMP,
        }
        data = _post_json(url, {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, payload)
        # Cloudflare wraps output in {"result": {"response": "..."}}
        result = data.get("result", {})
        return result.get("response") or result.get("text") or ""


# ── 5. Hugging Face (router, OpenAI-compatible) ───────────────────────
class HuggingFaceProvider(Provider):
    name = "huggingface"

    @property
    def model(self) -> str:
        return os.environ.get("HUGGINGFACE_MODEL", "meta-llama/Llama-3.1-8B-Instruct")

    def available(self) -> bool:
        return env_flag("HUGGINGFACE_API_KEY")

    def _raw_complete(self, system: str, prompt: str) -> str:
        return _openai_chat(
            "https://router.huggingface.co/v1/chat/completions",
            os.environ["HUGGINGFACE_API_KEY"], self.model, system, prompt,
        )


# ── 6. Generic OpenAI-compatible / open-source / self-hosted ──────────
class OpenAICompatProvider(Provider):
    """
    Any OpenAI-compatible /chat/completions endpoint. This is the open-source
    escape hatch: point it at Ollama, LM Studio, vLLM, llama.cpp, LocalAI, or a
    hosted OpenAI-compatible gateway (Together, DeepInfra, Fireworks, etc.).

    Config:
      OPENAI_COMPAT_BASE_URL   e.g. https://api.together.xyz  (or an Ollama root)
      OPENAI_COMPAT_API_KEY    optional (local servers usually need none)
      OPENAI_COMPAT_MODEL      e.g. meta-llama/Llama-3.1-8B-Instruct
    Convenience aliases for a local Ollama server:
      OLLAMA_BASE_URL          e.g. http://localhost:11434
      OLLAMA_MODEL             e.g. llama3.1
    """

    name = "openai_compat"

    @property
    def base_url(self) -> str:
        raw = (os.environ.get("OPENAI_COMPAT_BASE_URL") or os.environ.get("OLLAMA_BASE_URL", "")).strip().rstrip("/")
        if not raw:
            return ""
        if raw.endswith("/chat/completions"):
            return raw
        if raw.endswith("/v1"):
            return raw + "/chat/completions"
        return raw + "/v1/chat/completions"

    @property
    def model(self) -> str:
        return os.environ.get("OPENAI_COMPAT_MODEL") or os.environ.get("OLLAMA_MODEL", "llama3.1")

    def available(self) -> bool:
        return env_flag("OPENAI_COMPAT_BASE_URL") or env_flag("OLLAMA_BASE_URL")

    def _raw_complete(self, system: str, prompt: str) -> str:
        key = os.environ.get("OPENAI_COMPAT_API_KEY", "").strip() or "not-needed"
        return _openai_chat(self.base_url, key, self.model, system, prompt)


# Registry + default priority. Nothing is hard-wired to Google - the chain
# simply uses whichever provider's secrets are present first. Reorder or pin it
# with SIGNAL_AI_PROVIDER_ORDER / SIGNAL_AI_PROVIDER (see _resolve_order).
_PROVIDERS_BY_NAME: dict[str, type[Provider]] = {
    "gemini": GeminiProvider,
    "groq": GroqProvider,
    "openrouter": OpenRouterProvider,
    "cloudflare": CloudflareProvider,
    "huggingface": HuggingFaceProvider,
    "openai_compat": OpenAICompatProvider,
}
_DEFAULT_ORDER = ["gemini", "groq", "openrouter", "cloudflare", "huggingface", "openai_compat"]


def _resolve_order() -> list[str]:
    """
    Decide provider priority. Precedence:
      1. SIGNAL_AI_PROVIDER      - force one (or a short list), e.g. "groq"
      2. SIGNAL_AI_PROVIDER_ORDER- full custom order, e.g. "openai_compat,groq,gemini"
      3. built-in default order
    Either way the deterministic fallback still applies if none are available.
    """
    forced = os.environ.get("SIGNAL_AI_PROVIDER", "").strip().lower()
    if forced:
        return [p.strip() for p in forced.split(",") if p.strip()]
    custom = os.environ.get("SIGNAL_AI_PROVIDER_ORDER", "").strip().lower()
    if custom:
        return [p.strip() for p in custom.split(",") if p.strip()]
    return _DEFAULT_ORDER


def get_provider() -> Optional[Provider]:
    """Return the first *available* provider in the resolved order, or None."""
    for name in _resolve_order():
        cls = _PROVIDERS_BY_NAME.get(name)
        if cls is None:
            LOG.warning("unknown provider %r in order - skipping", name)
            continue
        provider = cls()
        if provider.available():
            LOG.info("AI provider selected: %s (model=%s)", provider.name, provider.model)
            return provider
    LOG.info("No AI provider configured → deterministic fallback mode.")
    return None


def provider_info(provider: Optional[Provider]) -> tuple[str, str, bool]:
    """(provider_name, model_name, fallback_used) for the provenance manifest."""
    if provider is None:
        return "deterministic", "none", True
    return provider.name, provider.model, False


# ══════════════════════════════════════════════════════════════════════
#  Source-grounding guard
# ══════════════════════════════════════════════════════════════════════
_NUM_RE = re.compile(r"\$?\d[\d,\.]*%?")
_URL_RE = re.compile(r"https?://\S+")


def _digit_core(token: str) -> str:
    return re.sub(r"[^\d]", "", token)


def _is_grounded(output: str, source_text: str) -> bool:
    """
    Reject output that introduces figures absent from the source (a common
    hallucination vector). Years and single digits are allowed; multi-digit
    numbers / money / percentages must appear in the source.
    """
    src_digits = set(_digit_core(t) for t in _NUM_RE.findall(source_text))
    for tok in _NUM_RE.findall(output):
        core = _digit_core(tok)
        if len(core) >= 2 and core not in _digit_core(source_text):
            # allow 4-digit years that appear anywhere in source
            if not (len(core) == 4 and core in src_digits):
                return False
    return True


def _strip_model_urls(text: str) -> str:
    """We control every link; never let the model inject its own."""
    return _URL_RE.sub("", text).replace("()", "").strip()


def _parse_json_block(text: str) -> Optional[dict]:
    if not text:
        return None
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        return json.loads(text[start:end])
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════
#  Deterministic (non-AI) fallbacks - always safe, source-tied
# ══════════════════════════════════════════════════════════════════════
_WHY_BY_CATEGORY = {
    "ai_model_companies": "Signals how frontier-model capabilities and access may shift for AI engineers and product teams.",
    "cloud_providers": "Relevant to cloud architects weighing platform capabilities, cost, and lock-in.",
    "data_engineering_platforms": "Directly affects data engineers evaluating lakehouse, warehouse, and pipeline tooling.",
    "open_source_foundations": "Matters for platform teams tracking the open-source dependencies under their stack.",
    "developer_platforms": "Useful for developers and DevEx teams assessing workflow and tooling changes.",
    "research_feeds": "Early-stage research that may inform future data and AI engineering practice.",
    "enterprise_technology": "Context for technology leaders planning enterprise architecture and vendor strategy.",
    "cybersecurity": "Security-relevant; worth a look for teams responsible for data and platform risk.",
    "databases": "Relevant to teams choosing or operating databases and query engines.",
    "mlops": "Practical for MLOps and platform engineers operationalizing models.",
    "aggregators": "Community-surfaced signal worth scanning for emerging developer sentiment.",
}


def _fallback_summary(item: NewsItem) -> str:
    base = item.summary or item.title
    return truncate(base, 300)


def _fallback_why(item: NewsItem) -> str:
    return _WHY_BY_CATEGORY.get(item.category, "Worth tracking for data and AI engineering practitioners.")


# ══════════════════════════════════════════════════════════════════════
#  Public API
# ══════════════════════════════════════════════════════════════════════
_NEWS_SYSTEM = (
    "You are a precise technology news editor writing for senior data and AI "
    "engineers. Summarize ONLY using the provided source text. Never add facts, "
    "numbers, product names, or claims not present in the source. No hype, no "
    "adjectives like 'revolutionary'. If the source is thin, keep it short."
)


def summarize_news_item(item: NewsItem, provider: Optional[Provider]) -> tuple[str, str]:
    """
    Return (summary, why_it_matters). Falls back to deterministic, source-tied
    text if there is no provider, the call fails, or the output fails the
    grounding guard.
    """
    fb_summary, fb_why = _fallback_summary(item), _fallback_why(item)
    if provider is None:
        return fb_summary, fb_why

    source_text = f"{item.title}. {item.summary}".strip()
    prompt = (
        f"SOURCE TITLE: {item.title}\n"
        f"SOURCE PUBLISHER: {item.source_name}\n"
        f"SOURCE TEXT: {item.summary or '(no abstract provided)'}\n\n"
        "Return STRICT JSON with two keys and nothing else:\n"
        '{"summary": "<1-2 factual sentences drawn only from the source>", '
        '"why_it_matters": "<1 sentence on why this matters to data engineers, AI '
        'engineers, cloud architects, or enterprise tech leaders - general '
        'interpretation only, invent no facts>"}'
    )
    raw = provider.complete(_NEWS_SYSTEM, prompt)
    parsed = _parse_json_block(raw or "")
    if not parsed:
        return fb_summary, fb_why

    summary = _strip_model_urls(str(parsed.get("summary", "")).strip())
    why = _strip_model_urls(str(parsed.get("why_it_matters", "")).strip())

    # Grounding gates.
    if not summary or len(summary) < 20 or not _is_grounded(summary, source_text):
        LOG.info("summary rejected by grounding guard for %r → fallback", truncate(item.title, 60))
        summary = fb_summary
    if not why or len(why) < 15 or not _is_grounded(why, source_text + " " + summary):
        why = fb_why

    return truncate(summary, 360), truncate(why, 240)


_INTRO_SYSTEM = (
    "You are the editor of a daily technology brief for senior engineers. Write a "
    "tight, executive-style opening paragraph. Use ONLY the headlines and themes "
    "provided. Do not invent facts, numbers, or events. 2-4 sentences, no bullet lists."
)


def write_intro(
    items: list[NewsItem],
    events: list[EventItem],
    history: Optional[HistoryItem],
    provider: Optional[Provider],
) -> str:
    headlines = "; ".join(truncate(i.title, 110) for i in items[:7])
    themes = ", ".join(sorted({t for i in items for t in i.tags})[:10])
    n = len(items)

    if provider is None or not headlines:
        # Deterministic, accurate assembly.
        if n == 0:
            return (
                "A quieter day for validated technology signals. Today's brief leans on the "
                "event radar and a moment from computing history while we wait for more "
                "corroborated stories to clear source review."
            )
        theme_str = f" spanning {themes}" if themes else ""
        return (
            f"Today's Daily Tech Signal tracks {n} source-reviewed "
            f"{'story' if n == 1 else 'stories'}{theme_str}. The highlights below focus on what "
            "changed and why it matters for data and AI engineering teams, followed by the "
            "event radar and this day in computing history."
        )

    prompt = (
        f"HEADLINES: {headlines}\n"
        f"THEMES: {themes or 'general technology'}\n"
        f"NUMBER OF STORIES: {n}\n\n"
        "Write the opening paragraph (2-4 sentences) for today's brief. Summarize the "
        "day's technology landscape at a high level using only these headlines/themes."
    )
    raw = provider.complete(_INTRO_SYSTEM, prompt)
    text = _strip_model_urls((raw or "").strip())
    if not text or len(text) < 40:
        return write_intro(items, events, history, None)  # deterministic path
    return truncate(text, 700)


_TAKE_SYSTEM = (
    "You are a senior data engineer and researcher writing a short, thoughtful closing "
    "note for your daily brief. Reflective, practical, first-person is fine. Use only the "
    "themes provided; invent no facts, numbers, or names. 2-3 sentences."
)


def write_takeaway(items: list[NewsItem], provider: Optional[Provider]) -> str:
    themes = ", ".join(sorted({t for i in items for t in i.tags})[:8]) or "the day's technology landscape"

    if provider is None or not items:
        return (
            "The throughline today is the same one that keeps showing up: capability is "
            "arriving faster than the data and platform discipline needed to operate it well. "
            "The teams that win won't be the ones that adopt the most tools, but the ones that "
            "keep their pipelines observable, their data governed, and their systems boring "
            "where it counts."
        )

    prompt = (
        f"THEMES TODAY: {themes}\n\n"
        "Write 'Aniket's Takeaway' - a 2-3 sentence closing reflection in a professional "
        "research-practitioner voice, grounded only in these themes."
    )
    raw = provider.complete(_TAKE_SYSTEM, prompt)
    text = _strip_model_urls((raw or "").strip())
    if not text or len(text) < 40:
        return write_takeaway(items, None)
    return truncate(text, 700)


if __name__ == "__main__":
    # Quick self-test: report which provider would be used.
    p = get_provider()
    name, model, fb = provider_info(p)
    print(f"provider={name} model={model} fallback_used={fb}")
