# llm/client.py
import os
import json

class LLMClient:
    def __init__(self):
        self.primary = os.getenv("ANTHROPIC_API_KEY")
        self.fallback = os.getenv("OPENAI_API_KEY")

    def run(self, prompt: str) -> str:
        """
        Stubbed.
        Replace with real provider calls.
        """
        if self.primary:
            return self._mock_response(prompt)
        if self.fallback:
            return self._mock_response(prompt)
        raise RuntimeError("No LLM API keys configured")

    def _mock_response(self, prompt: str) -> str:
        # Deterministic fake output for development
        # TODO: replace with real output
        return json.dumps({
            "is_real_issue": True,
            "confidence": 0.85,
            "reasoning": "Pattern matches known unsafe usage."
        })
