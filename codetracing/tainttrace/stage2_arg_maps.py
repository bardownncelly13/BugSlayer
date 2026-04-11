from llm import llm_json

SYSTEM = """You extract argument mappings from a single callsite.
Return ONLY valid JSON. No markdown.
"""

USER_TMPL = """Extract argument mapping for a specific call from the snippet.

language: {language}
caller_parameters: {caller_parameters}
callee_parameters: {callee_parameters}

snippet (contains line numbers; the call is on/near the reported call line):
{snippet}

Return JSON with keys:
- mapping: object mapping callee_param_index (string, "0","1",...) -> caller_argument_expression (string)
- by_name: object mapping callee_param_name -> caller_argument_expression (string), may be empty
- confidence: 0..1
- notes: short

If multiple calls appear, choose the one that best matches the callee function name.
"""

def build_argmap(language, caller_parameters, callee_parameters, snippet) -> dict:
    user = USER_TMPL.format(
        language=language or "",
        caller_parameters=caller_parameters or "",
        callee_parameters=callee_parameters or "",
        snippet=snippet or "",
    )
    print("Calling LLM for arg map...")
    return llm_json(SYSTEM, user)