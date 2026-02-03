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

        .
        Output a unified diff only.
        """
        vulrability = "find it yourself " #submit real vulnerability 
        sys = f"""you are a code vulnrability fixer and need to submit new code for the lines of codes submitted. We have determined\n 
        that the vulnerability is {context} return a json output and nothings else with minimal changes to the code. Make sure function names \n
        are the same and the code would work in the full codebase if overrides whats currently there
        
        """

        raw = self.llm.run(sys, prompt)
        return PatchResult(
            diff=raw,
            risk="low",
            requires_human=True
        )
