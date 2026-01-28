from typing import List, Dict

def scan_diff(diff: str) -> List[Dict]:
    """
    Pretend scanner output.
    Replace this with a real tool later.
    """
    # TODO: Replace with real tool
    findings = []
    if "eval(" in diff:
        findings.append({
            "rule_id": "PY-EVAL",
            "message": "Use of eval",
            "severity": "HIGH",
        })
    return findings
