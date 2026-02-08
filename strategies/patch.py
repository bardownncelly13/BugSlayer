import json
from llm.client import LLMClient
from models import PatchResult
from strategies.base import Strategy, PatchResult

class PatchStrategy(Strategy):
    def __init__(self):
        self.llm = LLMClient()

    def run(self, context):
        file = context["file"]
        finding = context["finding"]
        diff = context.get("diff", "")

        sys = """
You are a security-focused code remediation agent.

Your task:
- Propose the smallest possible fix for the vulnerability.
- Do NOT rewrite the entire file.
- Do NOT change unrelated logic.
- Do NOT include explanations.

Output JSON only, in this exact format:
{
  "old": "<exact code snippet to replace>",
  "new": "<secure replacement code snippet>",
  "risk": "low | medium | high"
}

Rules:
- "old" MUST appear verbatim in the file.
- Make exactly one replacement.
"""


        prompt = f"""
File: {file}

Security finding:
Rule ID: {finding.get("check_id")}
Message: {finding.get("extra", {}).get("message")}

Relevant diff context (may be partial):
{diff}
"""

        raw = self.llm.run(sys, prompt)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError("PatchStrategy: LLM did not return valid JSON")

        return PatchResult(
            file=file,
            old=data["old"],
            new=data["new"],
            risk=data["risk"],
            requires_human=(data["risk"] != "low"),
        )
