from pydantic import BaseModel

class TriageResult(BaseModel):
    is_real_issue: bool
    confidence: float
    reasoning: str


class PatchResult(BaseModel):
    diff: str
    risk: str
    requires_human: bool
