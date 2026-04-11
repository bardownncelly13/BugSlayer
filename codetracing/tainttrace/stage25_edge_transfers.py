from llm import llm_json

SYSTEM = """You are performing interprocedural taint-flow extraction for security analysis.
Return ONLY valid JSON. No markdown.

Definitions:
- "tainted" means attacker-controlled or untrusted input.
- You are analyzing ONE callsite where caller calls callee.
- Your job: determine which caller expressions flow into which callee parameters at this callsite,
  and whether the value passed is still tainted or has been validated/sanitized in a way that removes attacker control.

IMPORTANT: taint_from vocabulary must be normalized.
Use ONLY:
- "param:<name>"                e.g. "param:s"
- "source:argv"
- "source:stdin"
- "source:http"
- "source:file"
- "source:ipc"
- "source:env:<VAR>"            e.g. "source:env:AZURE_DEVOPS_USER"
- "unknown"
"""

USER_TMPL = """language: {language}

CALLER:
signature_parameters: {caller_parameters}
body:
{caller_body}

CALLEE:
signature_parameters: {callee_parameters}
body:
{callee_body}

CALLSITE SNIPPET (line-numbered context; call occurs here):
{snippet}

TASK:
Return JSON with keys:
- flows: list of objects, each:
  - callee_param_index: integer (0-based)
  - callee_param_name: string ("" if unknown)
  - caller_expression: string (expression passed at this callsite)
  - taint_from: list of strings (MUST follow the normalized vocabulary from system prompt)
  - tainted: boolean
      true  => the value passed is still attacker-controlled / untrusted
      false => the value passed is no longer attacker-controlled due to strong validation/sanitization
  - sanitizer_kind: one of ["none","escape","allowlist","length_check","bounds_copy","type_check","normalize","other"]
  - sanitizer_evidence: string (short quote) or ""
  - transform: one of ["identity","cast","encode","escape","allowlist","length_check","bounds_copy","unknown"]
- blocks_on_invalid: boolean (true if caller checks/returns/throws before the call on invalid input)
- confidence: 0..1
- notes: short string

Guidance:
- If caller passes argv[...] / input() / env var / req.body etc, include a source:* in taint_from and set tainted=true unless clearly sanitized.
- If caller passes a parameter directly, include "param:<name>".
- If unsure, set tainted=true and include "unknown".
"""

def build_edge_transfer(language, caller_parameters, caller_body, callee_parameters, callee_body, snippet) -> dict:
    user = USER_TMPL.format(
        language=language or "",
        caller_parameters=caller_parameters or "",
        caller_body=caller_body or "",
        callee_parameters=callee_parameters or "",
        callee_body=callee_body or "",
        snippet=snippet or "",
    )
    return llm_json(SYSTEM, user)