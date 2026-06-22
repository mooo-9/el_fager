from abc import ABC, abstractmethod

class BaseAgent(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Agent identifier, e.g. 'screen'"""

    @property
    @abstractmethod
    def description(self) -> str:
        """One-line description of what this agent handles."""

    @abstractmethod
    def run(self, task: str) -> str:
        """Execute the task and return a plain-text result."""
