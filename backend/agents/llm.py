"""LLM factory with timeout wrapper and robust JSON extraction."""
from __future__ import annotations
import json
import logging
import re
from typing import Type, TypeVar
from pydantic import BaseModel, ValidationError

log = logging.getLogger("astroagent.llm")
T = TypeVar("T", bound=BaseModel)


def get_llm(model: str, base_url: str, temperature: float = 0.1, timeout: int = 90):
    from langchain_ollama import OllamaLLM
    return OllamaLLM(
        model=model,
        base_url=base_url,
        temperature=temperature,
        timeout=timeout,
    )


def call_llm(prompt: str, model: str, base_url: str,
             timeout: int = 90, temperature: float = 0.1) -> str:
    """Call LLM with explicit timeout. Returns raw string or raises."""
    llm = get_llm(model, base_url, temperature=temperature, timeout=timeout)
    return llm.invoke(prompt)


def parse_json_output(raw: str, schema: Type[T]) -> T:
    """
    Extract JSON from LLM output and validate against Pydantic schema.
    Strips markdown fences, finds first JSON object, validates.
    Raises ValueError with clear message on failure.
    """
    text = raw.strip()
    # Strip ``` fences
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text).strip()

    # Find outermost JSON object
    start = text.find("{")
    end   = text.rfind("}") + 1
    if start < 0 or end <= start:
        raise ValueError(
            f"No JSON object found in LLM output for {schema.__name__}. "
            f"First 200 chars: {raw[:200]!r}"
        )

    try:
        data = json.loads(text[start:end])
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parse error for {schema.__name__}: {e}. "
                         f"Extracted: {text[start:end][:200]!r}")

    try:
        return schema(**data)
    except ValidationError as e:
        raise ValueError(f"Pydantic validation error for {schema.__name__}: {e}")
