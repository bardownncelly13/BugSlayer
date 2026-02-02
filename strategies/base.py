# strategies/base.py
from abc import ABC, abstractmethod

class Strategy(ABC):
    @abstractmethod
    def run(self, context: dict) -> dict | None:
        pass
