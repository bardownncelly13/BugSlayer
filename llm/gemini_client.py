import os
import random
import sys
import time

def _is_retryable_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        token in text
        for token in [
            "exhausted",
            "rate limit",
            "rate-limit",
            "timeout",
            "timed out",
            "temporarily unavailable",
            "unavailable",
            "internal",
            "503",
            "429",
            "server error",
            "service unavailable",
        ]
    )


def gemini_text(system: str, prompt: str, model: str = "gemini-2.0-flash") -> str:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    from google import genai

    max_retries = int(os.getenv("GEMINI_MAX_RETRIES", "5"))
    base_delay = float(os.getenv("GEMINI_RETRY_BASE_SECONDS", "1"))
    max_delay = float(os.getenv("GEMINI_RETRY_MAX_SECONDS", "64"))
    verbose = os.getenv("GEMINI_RETRY_VERBOSE", "false").lower() in ("1", "true", "yes")

    client = genai.Client(api_key=api_key)
    full = f"{system}\n\n{prompt}" if system else prompt

    last_error = None
    for attempt in range(max_retries + 1):
        try:
            resp = client.models.generate_content(model=model, contents=full)
            content = getattr(resp, "text", str(resp))
            return content or ""
        except Exception as exc:
            last_error = exc
            if attempt == max_retries or not _is_retryable_error(exc):
                raise

            delay = min(max_delay, base_delay * (2 ** attempt))
            jitter = delay * 0.2
            sleep_time = max(0.0, delay + random.uniform(-jitter, jitter))
            if verbose:
                print(
                    f"[gemini_client] attempt {attempt + 1}/{max_retries + 1} failed: {exc}. "
                    f"Retrying after {sleep_time:.1f}s.",
                    file=sys.stderr,
                    flush=True,
                )
            time.sleep(sleep_time)

    raise last_error