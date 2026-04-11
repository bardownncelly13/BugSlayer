from llm import llm_json

SYSTEM = """You are a security auditor.
Return ONLY valid JSON. No markdown.
"""

USER_TMPL = """Analyze the vulnerable function and produce a vulnerability contract.

language: {language}
vuln_issue: {vuln_issue}
vuln_message: {vuln_message}

function_body:
{body}

Return JSON with keys:
- sink_type: one of ["buffer_overflow","cmd_injection","sql_injection","xss","deserialization","path_traversal","format_string","other"]
- dangerous_operations: list of strings (evidence, e.g. "strcpy(buf,s)", "eval(x)")
- tainted_inputs: list of parameter names OR ["unknown"] if not clear
- required_mitigations: list of constraints/mitigations that make it safe
- notes: short
- confidence: 0..1
"""

def build_contract(language, vuln_issue, vuln_message, body) -> dict:
    user = USER_TMPL.format(
        language=language or "",
        vuln_issue=vuln_issue or "",
        vuln_message=vuln_message or "",
        body=body or "",
    )
    print("Calling LLM for vuln contract...")
    return llm_json(SYSTEM, user)