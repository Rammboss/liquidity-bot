from abc import ABC, abstractmethod


class BasicTask(ABC):
  def __init__(self, priority: int = 10):
    self.priority = priority

  @abstractmethod
  async def run(self):
    """Override this method to implement the task's logic."""
    pass

  def build_control_message(self) -> str | None:
    """Optional aggregated status message consumed by ControlService."""
    return None
