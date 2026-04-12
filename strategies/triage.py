import json
from llm.client import LLMClient
from models import TriageResult
from strategies.base import Strategy
from strategies.llm_debug import print_llm_context_if_enabled

class TriageStrategy(Strategy):
    def __init__(self):
        self.llm = LLMClient()

    def run(self, context: dict) -> TriageResult | None:
        finding_repr = context["finding"]
        if isinstance(finding_repr, dict):
            finding_repr = json.dumps(finding_repr, indent=2, default=str)

        prompt = f"""
        Scanner reported:
        {finding_repr}

        Code context:
        {context['diff']}

        Decide if this is a real issue.
        Return JSON with:
        - is_real_issue (bool)
        - confidence (0-1)
        - reasoning (string)
        """
        sys = (
            "You are a triage assistant. Given the scanner report and code context, "
            "respond ONLY with JSON of the form:\n"
            '{ "is_real_issue": boolean, "confidence": number, "reasoning": string }'
        )

        print_llm_context_if_enabled(
            f"TriageStrategy file={context.get('file', '?')}",
            sys,
            prompt,
        )

        raw = self.llm.run(sys, prompt)
        # model_validate is currently not doing anything
        return TriageResult.model_validate(json.loads(raw))
