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
    client = genai.Client(api_key=api_key)

    full = f"{system}\n\n{prompt}"
    resp = client.models.generate_content(model=model, contents=full)
    return resp.text or ""