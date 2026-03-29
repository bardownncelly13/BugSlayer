# strategies/base.py
from abc import ABC, abstractmethod
from typing import List, Tuple

class Strategy(ABC):
    @abstractmethod
    def run(self, context: dict) -> dict | None:
        pass


class PatchResult:
    """Result of a patch: one or more (old, new) replacements in the same file."""

    def __init__(
        self,
        file: str,
        replacements: List[Tuple[str, str]],
        risk: str,
        requires_human: bool = True,
    ):
        self.file = file
        self.replacements = list(replacements)  # [(old1, new1), (old2, new2), ...]
        self.risk = risk
        self.requires_human = requires_human

    @property
    def old(self) -> str:
        """First 'old' snippet (for backward compatibility)."""
        return self.replacements[0][0] if self.replacements else ""

    @property
    def new(self) -> str:
        """First 'new' snippet (for backward compatibility)."""
        return self.replacements[0][1] if self.replacements else ""

