import json
from llm.client import LLMClient
from models import TriageResult
from strategies.base import Strategy

class TriageStrategy(Strategy):
    def __init__(self):
        self.llm = LLMClient()

    def run(self, context: dict) -> TriageResult | None:
        prompt = f"""
        Scanner reported:
        {context['finding']}

        Diff:
        {context['diff']}

        Decide if this is a real issue.
        Return JSON with:
        - is_real_issue (bool)
        - confidence (0-1)
        - reasoning (string)
        """

        raw = self.llm.run(prompt)
        # model_validate is currently not doing anything
        return TriageResult.model_validate(json.loads(raw))
