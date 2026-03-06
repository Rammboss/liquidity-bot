from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict


class PerformanceSnapshot(TypedDict):
  apu: float
  total_profit_usdc: float
  eth_balance: float
  eurc_balance: float
  usdc_balance: float


class RuntimeState:
  def __init__(self):
    self.sleep_mode = False
    self._task_snapshot_provider: Callable[[], list[str]] | None = None
    self._task_event_buffer: list[str] = []
    self._performance_snapshot: PerformanceSnapshot | None = None

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

  def set_performance_snapshot(self, performance_snapshot: PerformanceSnapshot) -> None:
    self._performance_snapshot = performance_snapshot

  def get_performance_snapshot(self) -> PerformanceSnapshot | None:
    return self._performance_snapshot
