from llm import llm_json

SYSTEM = """You summarize functions for interprocedural taint analysis.
Return ONLY valid JSON. No markdown.
"""

USER_TMPL = """Summarize this function for taint tracking.

language: {language}
parameters: {parameters}

function_body:
{body}

Return JSON with keys:
- sources: list of objects {{kind, evidence}} where kind in ["argv","stdin","env","http","file","ipc","other","none"]
- sanitizers: list of objects {{kind, affects, evidence}} where affects is list of parameter/variable names
- kills_taint: list of objects {{var, evidence}} (overwritten with constant / dropped)
- passes_through: boolean (if tainted input can flow to outputs/callees)
- notes: short
- confidence: 0..1
"""

def build_summary(language, parameters, body) -> dict:
    user = USER_TMPL.format(
        language=language or "",
        parameters=parameters or "",
        body=body or "",
    )
    print("Calling LLM for func summary...")
    return llm_json(SYSTEM, user)