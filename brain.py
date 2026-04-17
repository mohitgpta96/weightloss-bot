from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from anthropic import AsyncAnthropic
from groq import AsyncGroq
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrainProvider:
    name: str
    kind: str
    model: str
    client: Any


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _provider_order() -> list[str]:
    raw = _env("AI_PROVIDER_ORDER", "groq,anthropic,openai,deepseek")
    order = [part.strip().lower() for part in raw.split(",") if part.strip()]
    # Keep the first occurrence of each provider only.
    seen: set[str] = set()
    deduped: list[str] = []
    for name in order:
        if name not in seen:
            deduped.append(name)
            seen.add(name)
    return deduped


@lru_cache(maxsize=1)
def _providers() -> tuple[BrainProvider, ...]:
    providers: list[BrainProvider] = []
    for name in _provider_order():
        if name == "groq":
            api_key = _env("GROQ_API_KEY")
            if api_key:
                providers.append(
                    BrainProvider(
                        name="groq",
                        kind="openai_compatible",
                        model=_env("GROQ_MODEL", "llama-3.3-70b-versatile"),
                        client=AsyncGroq(api_key=api_key),
                    )
                )
        elif name == "openai":
            api_key = _env("OPENAI_API_KEY")
            if api_key:
                kwargs: dict[str, Any] = {"api_key": api_key}
                base_url = _env("OPENAI_BASE_URL")
                if base_url:
                    kwargs["base_url"] = base_url
                providers.append(
                    BrainProvider(
                        name="openai",
                        kind="openai_compatible",
                        model=_env("OPENAI_MODEL", "gpt-4.1"),
                        client=AsyncOpenAI(**kwargs),
                    )
                )
        elif name == "deepseek":
            api_key = _env("DEEPSEEK_API_KEY")
            if api_key:
                providers.append(
                    BrainProvider(
                        name="deepseek",
                        kind="openai_compatible",
                        model=_env("DEEPSEEK_MODEL", "deepseek-chat"),
                        client=AsyncOpenAI(
                            api_key=api_key,
                            base_url=_env("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                        ),
                    )
                )
        elif name == "anthropic":
            api_key = _env("ANTHROPIC_API_KEY")
            if api_key:
                providers.append(
                    BrainProvider(
                        name="anthropic",
                        kind="anthropic",
                        model=_env("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
                        client=AsyncAnthropic(api_key=api_key),
                    )
                )
    return tuple(providers)


def available_providers() -> list[str]:
    return [provider.name for provider in _providers()]


def _anthropic_messages(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role", "user")
        if role not in {"user", "assistant"}:
            continue
        converted.append({"role": role, "content": message.get("content", "")})
    return converted


def _extract_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


def _extract_text(response: Any, provider: BrainProvider) -> str:
    if provider.kind == "anthropic":
        blocks = getattr(response, "content", [])
        parts: list[str] = []
        for block in blocks:
            piece = getattr(block, "text", "")
            if piece:
                parts.append(piece)
        return "".join(parts).strip()
    return response.choices[0].message.content.strip()


async def generate_text(
    *,
    system: str,
    messages: list[dict[str, str]],
    max_tokens: int = 300,
    temperature: float = 0.7,
) -> str:
    """Generate plain text from the best available provider."""
    providers = _providers()
    if not providers:
        raise RuntimeError("No AI provider configured")

    last_error: Exception | None = None
    for provider in providers:
        try:
            if provider.kind == "anthropic":
                response = await provider.client.messages.create(
                    model=provider.model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=_anthropic_messages(messages),
                )
            else:
                payload = [{"role": "system", "content": system}] if system else []
                payload.extend(messages)
                response = await provider.client.chat.completions.create(
                    model=provider.model,
                    messages=payload,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            return _extract_text(response, provider)
        except Exception as exc:  # pragma: no cover - provider fallback path
            last_error = exc
            logger.warning("AI provider %s failed for text generation: %s", provider.name, exc)
            continue

    if last_error:
        raise last_error
    raise RuntimeError("No AI provider could generate text")


async def generate_json(
    *,
    system: str,
    messages: list[dict[str, str]],
    max_tokens: int = 400,
    temperature: float = 0.7,
) -> dict[str, Any]:
    """Generate structured JSON from the best available provider."""
    providers = _providers()
    if not providers:
        raise RuntimeError("No AI provider configured")

    last_error: Exception | None = None
    for provider in providers:
        try:
            if provider.kind == "anthropic":
                response = await provider.client.messages.create(
                    model=provider.model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=system,
                    messages=_anthropic_messages(messages),
                )
                raw = _extract_text(response, provider)
                return _extract_json(raw)

            payload = [{"role": "system", "content": system}] if system else []
            payload.extend(messages)
            try:
                response = await provider.client.chat.completions.create(
                    model=provider.model,
                    messages=payload,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )
            except TypeError:
                response = await provider.client.chat.completions.create(
                    model=provider.model,
                    messages=payload,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            raw = _extract_text(response, provider)
            return _extract_json(raw)
        except Exception as exc:  # pragma: no cover - provider fallback path
            last_error = exc
            logger.warning("AI provider %s failed for JSON generation: %s", provider.name, exc)
            continue

    if last_error:
        raise last_error
    raise RuntimeError("No AI provider could generate JSON")

