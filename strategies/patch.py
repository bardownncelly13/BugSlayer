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
- Make a minimal change to fix the vulnerability.
- You may add imports or helper code if strictly necessary to make the fix valid.
- Do NOT rewrite unrelated logic.
- Output only JSON in this format:
{
  "old": "<exact code snippet to replace>",
  "new": "<secure replacement code snippet>",
  "risk": "low | medium | high"
}

Rules:
- "old" MUST appear verbatim in the file.
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
