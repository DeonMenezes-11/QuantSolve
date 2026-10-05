"""Settings loaded from the project's ``.env`` file and environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "runs"
RESULTS_DIR = PROJECT_ROOT / "results"

# Explicit path: a bare load_dotenv() searches from the caller's file and fails
# when Python is started from stdin or from another working directory.
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    model: str = "gpt-4.1-mini"
    max_attempts: int = 5          # QS_MAX_ATTEMPTS
    timeout_s: float = 10.0        # QS_TIMEOUT, wall-clock limit for one sandbox run
    temperature: float = 0.2       # solver temperature (low: we want careful code)
    reflect_temperature: float = 0.3
    nudge_temperature: float = 0.8  # used after the loop guard fires, to break repetition
    max_tokens: int = 1800         # completion cap per LLM call
    llm_retries: int = 3           # attempts per LLM call on transient API errors


def load_settings(**overrides: object) -> Settings:
    """Build settings from the environment; keyword overrides that are not None win."""
    base = Settings(
        model=os.getenv("OPENAI_MODEL", Settings.model),
        max_attempts=int(os.getenv("QS_MAX_ATTEMPTS", Settings.max_attempts)),
        timeout_s=float(os.getenv("QS_TIMEOUT", Settings.timeout_s)),
        temperature=float(os.getenv("QS_TEMPERATURE", Settings.temperature)),
    )
    return replace(base, **{k: v for k, v in overrides.items() if v is not None})


def has_api_key() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))
