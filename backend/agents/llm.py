"""Ollama LLM factory + robust JSON output parser."""
from __future__ import annotations
import re
import json
import logging
import httpx
from typing import Any

log = logging.getLogger(__name__)


def call_llm(
    prompt: str,
    model: str,
    system: str = "",
    ollama_url: str = "http://localhost:11434",
    timeout: int = 60,
) -> str:
    """Synchronous Ollama chat call. Returns text content."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                f"{ollama_url}/api/chat",
                json={"model": model, "stream": False, "messages": messages},
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"].strip()
    except httpx.ConnectError:
        raise RuntimeError("Ollama not running — start with: ollama serve")
    except Exception as e:
        log.error(f"LLM call failed: {e}")
        raise


def parse_json_output(text: str, schema: type | None = None) -> dict[str, Any]:
    """Strip markdown fences, extract JSON object, optionally validate."""
    # Remove markdown code fences
    text = re.sub(r"```(?:json)?", "", text).strip()
    # Find the first {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in LLM output: {text[:200]}")
    data = json.loads(match.group())
    if schema is not None:
        return schema(**data).model_dump()
    return data


async def get_available_models(ollama_url: str = "http://localhost:11434") -> list[dict]:
    """Return list of installed Ollama models with metadata."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{ollama_url}/api/tags")
            resp.raise_for_status()
            models = resp.json().get("models", [])

        # Sort by recommended order for astronomy reasoning
        preferred = ["llama3.1", "llama3.2", "mistral", "gemma3", "llama3", "phi3"]
        def sort_key(m):
            name = m.get("name", "")
            for i, p in enumerate(preferred):
                if p in name:
                    return i
            return len(preferred)

        return sorted(models, key=sort_key)
    except Exception:
        return []
