from __future__ import annotations

from collections.abc import Callable


class RuntimeState:
  def __init__(self):
    self.sleep_mode = False
    self._task_snapshot_provider: Callable[[], list[str]] | None = None
    self._task_event_buffer: list[str] = []

  def set_sleep_mode(self, enabled: bool):
    self.sleep_mode = enabled

  def is_sleep_mode(self) -> bool:
    return self.sleep_mode

  def register_task_snapshot_provider(self, provider: Callable[[], list[str]]) -> None:
    self._task_snapshot_provider = provider

  def get_task_snapshot(self) -> list[str]:
    if not self._task_snapshot_provider:
      return []
    return self._task_snapshot_provider()

  def push_task_event(self, message: str) -> None:
    if message:
      self._task_event_buffer.append(message)

  def pop_task_events(self) -> list[str]:
    events = self._task_event_buffer.copy()
    self._task_event_buffer.clear()
    return events
