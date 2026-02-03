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

        finding = context["finding"]
        prompt = f"""
        The following code change introduced a security vulnerability.

        Vulnerability:
        - Rule ID: {finding["check_id"]}
        - Description: {finding["extra"]["message"]}
        - Severity: {finding["extra"]["severity"]}

        Code diff:
        {context["diff"]}

        Fix the vulnerability by modifying the diff above.
        Output a unified diff only.

        """
        vulrability = "???" #submit real vulnerability 
        # Make more ideal prompts
        sys = f"""You are an automated security patch generator.

        Rules you MUST follow:
        - Output a valid unified diff and nothing else.
        - Modify only the lines shown in the provided diff.
        - Make the smallest possible change to remove the vulnerability.
        - Do NOT rename functions, variables, or files.
        - Do NOT reformat code or change unrelated logic.
        - Do NOT add new dependencies or imports unless required to fix the vulnerability.
        - The resulting code must run correctly when applied to the full codebase.

        If the vulnerability cannot be fixed safely under these rules,
        output an empty diff.

        """

        raw = self.llm.run(sys, prompt)
        return PatchResult(
            diff=raw,
            risk="low",
            requires_human=True
        )
