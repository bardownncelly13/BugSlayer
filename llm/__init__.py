import json

_llm_client = None


def _get_llm_client():
    global _llm_client
    if _llm_client is None:
        from .client import LLMClient
        _llm_client = LLMClient()
    return _llm_client


def llm_json(system: str, user: str) -> dict:
    raw = _get_llm_client().run(system, user)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned invalid JSON: {raw[:4000]}") from exc
