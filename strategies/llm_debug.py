"""Opt-in logging of prompts sent to the LLM."""

import os

_dotenv_loaded = False


def _ensure_dotenv() -> None:
    """So DEBUG_LLM_CONTEXT in .env works even if nothing called load_dotenv yet."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


def _truthy_env(name: str) -> bool:
    _ensure_dotenv()
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def print_llm_context_if_enabled(
    stage: str,
    system: str,
    user: str,
    *,
    max_system_chars: int = 8000,
    max_user_chars: int = 12000,
) -> None:
    if not _truthy_env("DEBUG_LLM_CONTEXT"):
        return

    sep = "=" * 72

    def trunc(s: str, n: int) -> str:
        if len(s) <= n:
            return s
        return s[:n] + "\n... [truncated]"

    print(f"\n{sep}\n[DEBUG_LLM_CONTEXT] {stage}\n{sep}")
    print("--- system ---")
    print(trunc(system, max_system_chars))
    print("--- user ---")
    print(trunc(user, max_user_chars))
    print(f"{sep}\n")
