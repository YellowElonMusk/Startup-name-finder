"""Optional LLM brainstorming ("bring your own API key").

Two provider families:

* ``anthropic`` - Claude via the official ``anthropic`` SDK.
* OpenAI-compatible chat-completions APIs (OpenAI, DeepSeek, Gemini,
  OpenRouter, Groq, local Ollama/LM Studio, ...), via plain HTTP.

The key lives only in this process's memory; nothing is written to disk.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from typing import Optional

import httpx

from .inspire import VIBES
from .net import ssl_context

__all__ = ["PROVIDERS", "AIConfig", "AIError", "configure", "current", "clear", "brainstorm"]

PROVIDERS: dict[str, dict[str, str]] = {
    "anthropic": {"label": "Anthropic (Claude)", "base_url": "", "model": "claude-opus-5"},
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "gpt-5-mini"},
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
    "gemini": {"label": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-2.5-flash"},
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "model": "openai/gpt-5-mini"},
    "groq": {"label": "Groq", "base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile"},
    "custom": {"label": "Other (OpenAI-compatible)", "base_url": "http://localhost:11434/v1", "model": ""},
}

# Claude models that accept the server-side refusal fallback ("default" mode).
_FALLBACK_MODELS = ("claude-opus-5", "claude-fable-5", "claude-fable-5-1")


class AIError(Exception):
    """User-presentable failure (bad key, unknown model, provider error)."""


@dataclass(frozen=True)
class AIConfig:
    provider: str
    api_key: str
    model: str
    base_url: str = ""

    def public(self) -> dict:
        tail = self.api_key[-4:] if len(self.api_key) >= 8 else ""
        return {
            "provider": self.provider,
            "label": PROVIDERS.get(self.provider, {}).get("label", self.provider),
            "model": self.model,
            "base_url": self.base_url,
            "key_hint": f"...{tail}" if tail else "set",
        }


_lock = threading.Lock()
_config: Optional[AIConfig] = None


def current() -> Optional[AIConfig]:
    return _config


def clear() -> None:
    global _config
    with _lock:
        _config = None


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

def _anthropic_client(cfg: AIConfig):
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise AIError("The 'anthropic' package is not installed (pip install anthropic).") from exc
    return anthropic, anthropic.Anthropic(
        api_key=cfg.api_key,
        http_client=anthropic.DefaultHttpxClient(verify=ssl_context()),
        timeout=180.0,
    )


def _anthropic_error(anthropic, exc: Exception) -> AIError:
    if isinstance(exc, anthropic.AuthenticationError):
        return AIError("Anthropic rejected the API key.")
    if isinstance(exc, anthropic.PermissionDeniedError):
        return AIError("This API key does not have access to that model.")
    if isinstance(exc, anthropic.NotFoundError):
        return AIError("Unknown Claude model id.")
    if isinstance(exc, anthropic.RateLimitError):
        return AIError("Anthropic rate limit hit - try again in a minute.")
    if isinstance(exc, anthropic.APIStatusError):
        return AIError(f"Anthropic error {exc.status_code}: {exc.message}")
    if isinstance(exc, anthropic.APIConnectionError):
        return AIError("Could not reach api.anthropic.com.")
    return AIError(f"{type(exc).__name__}: {exc}")


def _openai_base(cfg: AIConfig) -> str:
    base = (cfg.base_url or PROVIDERS.get(cfg.provider, {}).get("base_url", "")).rstrip("/")
    if not base:
        raise AIError("Base URL is required for this provider.")
    return base


def _openai_http(cfg: AIConfig) -> httpx.Client:
    return httpx.Client(
        timeout=180.0,
        verify=ssl_context(),
        headers={"Authorization": f"Bearer {cfg.api_key}", "User-Agent": "namestack/0.1"},
    )


def _http_error(resp: httpx.Response) -> AIError:
    try:
        body = resp.json()
        msg = (body.get("error") or {}).get("message") if isinstance(body.get("error"), dict) else body.get("error")
        msg = msg or body.get("message") or resp.text
    except ValueError:
        msg = resp.text
    if resp.status_code in (401, 403):
        return AIError(f"The provider rejected the API key ({resp.status_code}).")
    return AIError(f"Provider error {resp.status_code}: {str(msg)[:300]}")


# ---------------------------------------------------------------------------
# Configure (validates the key without spending tokens)
# ---------------------------------------------------------------------------

def configure(provider: str, api_key: str, model: str = "", base_url: str = "") -> AIConfig:
    global _config
    provider = (provider or "").strip().lower()
    if provider not in PROVIDERS:
        raise AIError(f"Unknown provider '{provider}'.")
    api_key = (api_key or "").strip()
    if not api_key and provider != "custom":
        raise AIError("Paste an API key first.")
    model = (model or PROVIDERS[provider]["model"]).strip()
    if not model:
        raise AIError("Enter a model name.")
    cfg = AIConfig(provider, api_key, model, (base_url or PROVIDERS[provider]["base_url"]).strip())

    if provider == "anthropic":
        anthropic, client = _anthropic_client(cfg)
        try:
            client.models.retrieve(model)
        except Exception as exc:  # noqa: BLE001 - mapped to a friendly message
            raise _anthropic_error(anthropic, exc) from exc
    else:
        try:
            with _openai_http(cfg) as http:
                resp = http.get(f"{_openai_base(cfg)}/models")
        except httpx.HTTPError as exc:
            raise AIError(f"Could not reach {_openai_base(cfg)}: {type(exc).__name__}") from exc
        if resp.status_code >= 400:
            raise _http_error(resp)

    with _lock:
        _config = cfg
    return cfg


# ---------------------------------------------------------------------------
# Brainstorm
# ---------------------------------------------------------------------------

def _schema(vibes: list[str]) -> dict:
    word = {
        "type": "object",
        "properties": {"word": {"type": "string"}, "meaning": {"type": "string"}},
        "required": ["word", "meaning"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "synonyms": {"type": "array", "items": {"type": "string"}},
            "latin": {"type": "array", "items": word},
            "greek": {"type": "array", "items": word},
            "names": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "vibe": {"type": "string", "enum": vibes},
                        "why": {"type": "string"},
                    },
                    "required": ["name", "vibe", "why"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["synonyms", "latin", "greek", "names"],
        "additionalProperties": False,
    }


def _prompt(seeds: list[str], vibes: list[str], per_vibe: int) -> str:
    vibe_lines = "\n".join(
        f'- "{v}": {VIBES[v].label} - {VIBES[v].blurb} (e.g. {VIBES[v].examples})' for v in vibes
    )
    return (
        "You are a startup naming expert helping a founder brainstorm brand names.\n\n"
        f"Theme / seed words: {', '.join(seeds)}\n\n"
        "The seed words are inspiration, not building blocks. First, expand the theme:\n"
        "- synonyms: 10-20 evocative English words related to the theme (metaphors welcome)\n"
        "- latin / greek: 5-12 real Latin and Greek words for the theme, transliterated to "
        "plain ASCII, each with its English meaning\n\n"
        f"Then propose about {per_vibe} names for EACH of these naming styles:\n{vibe_lines}\n\n"
        "Rules for names: lowercase a-z only, no spaces, hyphens or digits, 3-12 letters, "
        "easy to say and spell, not an existing famous brand. `why` is one short phrase "
        "explaining the idea. Favor names likely to have an available domain (avoid plain "
        "common dictionary words for every style except 'real')."
    )


def _parse_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise AIError("The model did not return JSON.")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise AIError("The model returned malformed JSON.") from exc


def _brainstorm_anthropic(cfg: AIConfig, prompt: str, schema: dict) -> dict:
    anthropic, client = _anthropic_client(cfg)
    output_config: dict = {"format": {"type": "json_schema", "schema": schema}}
    if not cfg.model.startswith("claude-haiku"):
        output_config["effort"] = "medium"
    kwargs: dict = {}
    if cfg.model in _FALLBACK_MODELS:
        kwargs = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    try:
        response = client.beta.messages.create(
            model=cfg.model,
            max_tokens=16000,
            output_config=output_config,
            messages=[{"role": "user", "content": prompt}],
            **kwargs,
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a friendly message
        raise _anthropic_error(anthropic, exc) from exc
    if response.stop_reason == "refusal":
        raise AIError("Claude declined this request.")
    if response.stop_reason == "max_tokens":
        raise AIError("The response was cut off; try fewer styles.")
    text = "".join(b.text for b in response.content if b.type == "text")
    return _parse_json(text)


def _brainstorm_openai(cfg: AIConfig, prompt: str) -> dict:
    body = {
        "model": cfg.model,
        "messages": [
            {"role": "system", "content": "Reply with a single JSON object with keys "
             "synonyms (string[]), latin ({word, meaning}[]), greek ({word, meaning}[]), "
             "names ({name, vibe, why}[]). No prose."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    url = f"{_openai_base(cfg)}/chat/completions"
    try:
        with _openai_http(cfg) as http:
            resp = http.post(url, json=body)
            if resp.status_code == 400 and "response_format" in resp.text:
                body.pop("response_format")
                resp = http.post(url, json=body)
    except httpx.HTTPError as exc:
        raise AIError(f"Could not reach {_openai_base(cfg)}: {type(exc).__name__}") from exc
    if resp.status_code >= 400:
        raise _http_error(resp)
    try:
        text = resp.json()["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AIError("Unexpected response shape from the provider.") from exc
    return _parse_json(text)


def brainstorm(seeds: list[str], vibes: list[str], per_vibe: int = 15) -> dict:
    """Ask the configured LLM for related concepts and names.

    Returns ``{"synonyms": [...], "latin": [...], "greek": [...], "names": [...]}``.
    """
    cfg = _config
    if cfg is None:
        raise AIError("AI is not configured.")
    vibes = [v for v in vibes if v in VIBES] or list(VIBES)
    prompt = _prompt(seeds, vibes, per_vibe)
    if cfg.provider == "anthropic":
        data = _brainstorm_anthropic(cfg, prompt, _schema(vibes))
    else:
        data = _brainstorm_openai(cfg, prompt)

    names = []
    for item in data.get("names") or []:
        if not isinstance(item, dict):
            continue
        name = re.sub(r"[^a-z]", "", str(item.get("name", "")).lower())
        vibe = item.get("vibe") if item.get("vibe") in vibes else vibes[0]
        if 3 <= len(name) <= 14:
            names.append({"name": name, "vibe": vibe, "why": str(item.get("why", ""))[:120]})
    return {
        "synonyms": [str(s) for s in data.get("synonyms") or [] if isinstance(s, str)],
        "latin": [x for x in data.get("latin") or [] if isinstance(x, (dict, str))],
        "greek": [x for x in data.get("greek") or [] if isinstance(x, (dict, str))],
        "names": names,
    }
