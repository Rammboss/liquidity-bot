from abc import ABC, abstractmethod

class BasicTask(ABC):
    def __init__(self, priority: int = 10):
        self.priority = priority

    @abstractmethod
    async def run(self):
        """Override this method to implement the task's logic."""
        pass
