# strategies/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

class Strategy(ABC):
    @abstractmethod
    def run(self, context: dict) -> dict | None:
        pass

@dataclass
class PatchResult:
    def __init__(self, file: str, old: str, new: str, risk: str, requires_human: bool = True):
        self.file = file
        self.old = old
        self.new = new
        self.risk = risk
        self.requires_human = requires_human

