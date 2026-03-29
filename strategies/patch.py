import json
from llm.client import LLMClient
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
- Make minimal changes to fix the vulnerability.
- You may add imports or helper code if strictly necessary to make the fix valid.
- Do NOT rewrite unrelated logic.
- Each "old" snippet MUST appear verbatim in the file.
- Do NOT simply comment out the old code; your fix must preserve program logic.
- Only remove or replace code in a way that keeps the function/file operational.

Output only JSON in one of these formats:

Single replacement:
{{
  "old": "<exact code snippet to replace>",
  "new": "<secure replacement code snippet>",
  "risk": "low | medium | high"
}}

Multiple replacements (use when the fix requires several edits in the same file, e.g. add import + fix call, or fix two occurrences):
{{
  "replacements": [
    {{ "old": "<exact snippet 1>", "new": "<replacement 1>" }},
    {{ "old": "<exact snippet 2>", "new": "<replacement 2>" }}
  ],
  "risk": "low | medium | high"
}}

Rules:
- Each "old" MUST appear verbatim in the file; list them in the order they appear in the file (top to bottom) so they can be applied correctly.
- Prefer a single replacement when possible; use multiple only when necessary (e.g. adding an import and fixing the vulnerable line).
- Multi-line replacements are allowed. In JSON, represent line breaks inside the "old" and "new" strings using the escaped sequence `\\n` (example: `"new": "line1();\\nline2();"`).
- If `old` is a single line and `new` expands to multiple lines, ensure each subsequent line is indented to match the original line's indentation (the patcher also tries to preserve indentation, but this makes results more reliable).

Previous failed attempts (do NOT repeat these changes):
{failure_msg}
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

        risk = data.get("risk", "medium")
        if "replacements" in data:
            replacements = [(r["old"], r["new"]) for r in data["replacements"]]
        else:
            replacements = [(data["old"], data["new"])]

        if not replacements:
            raise ValueError("PatchStrategy: LLM returned no replacements")

        return PatchResult(
            file=file,
            replacements=replacements,
            risk=risk,
            requires_human=(risk != "low"),
        )
