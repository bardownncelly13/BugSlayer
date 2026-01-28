import json
from llm.client import LLMClient
from models import PatchResult
from strategies.base import Strategy

class PatchStrategy(Strategy):
    def __init__(self):
        self.llm = LLMClient()

    def run(self, context: dict) -> PatchResult | None:
        # We can fiddle with this confidence interval later
        if context["triage"].confidence < 0.8:
            return None  # CRS-style early exit

        prompt = f"""
        Given this diff and issue:
        {context['diff']}

        Propose a minimal fix.
        Output a unified diff only.
        """

        raw = self.llm.run(prompt)
        return PatchResult(
            diff=raw,
            risk="low",
            requires_human=True
        )
