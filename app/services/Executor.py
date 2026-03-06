import asyncio
import traceback

from common.logger import get_logger
from execution.BasicTask import BasicTask
from execution.tasks.CoinbaseWithdrawalTask import CoinbaseWithdrawalTask
from execution.tasks.WalletWithdrawalTask import WalletWithdrawalTask


class Executor:
  def __init__(self, runtime_state=None):
    self.logger = get_logger()
    self.runtime_state = runtime_state
    self.queue: list[BasicTask] = []

  def clear_queue(self):
    if self.queue:
      self.logger.warning(f"Clearing executor queue with {len(self.queue)} pending task(s).")
    self.queue.clear()

  def get_task_snapshot(self) -> list[str]:
    snapshot: list[str] = []
    for task in sorted(self.queue, key=lambda t: t.priority, reverse=True):
      amount = getattr(task, "amount", None)
      t1_amount = getattr(task, "t1_stat_amount", None)
      amount_details = ""
      if isinstance(amount, (int, float)):
        amount_details = f" amount={amount:.4f}"
      elif isinstance(t1_amount, (int, float)):
        amount_details = f" amount={t1_amount:.4f}"
      snapshot.append(f"{task.__class__.__name__}(prio={task.priority}{amount_details})")
    return snapshot

  def _collect_task_event(self, task: BasicTask) -> None:
    if not self.runtime_state:
      return

    event_message = task.build_control_message()
    if event_message:
      self.runtime_state.push_task_event(event_message)

  def _pick_parallel_withdrawal_tasks(self) -> list[BasicTask]:
    cb_task = next((task for task in self.queue if isinstance(task, CoinbaseWithdrawalTask)), None)
    wallet_task = next((task for task in self.queue if isinstance(task, WalletWithdrawalTask)), None)

    selected: list[BasicTask] = []
    if cb_task:
      selected.append(cb_task)
    if wallet_task:
      selected.append(wallet_task)
    return selected

  async def _run_tasks_parallel(self, tasks: list[BasicTask]) -> None:
    if not tasks:
      return

    self.logger.info(
      "Starting parallel withdrawal tasks: " + ", ".join(task.__class__.__name__ for task in tasks)
    )
    results = await asyncio.gather(*(task.run() for task in tasks), return_exceptions=True)

    for task, result in zip(tasks, results):
      if task in self.queue:
        self.queue.remove(task)

      if isinstance(result, Exception):
        self.logger.error(f"Task {task.__class__.__name__} failed: {result}")
      else:
        self.logger.info(f"Task {task.__class__.__name__} completed.")

      self._collect_task_event(task)

  async def run(self):
    self.clear_queue()

    while True:
      try:
        if self.runtime_state and self.runtime_state.is_sleep_mode():
          await asyncio.sleep(1)
          continue

        if self.queue:
          self.queue.sort(key=lambda t: t.priority)
          parallel_tasks = self._pick_parallel_withdrawal_tasks()
          if len(parallel_tasks) == 2:
            await self._run_tasks_parallel(parallel_tasks)
            continue

          task = self.queue[-1]
          self.logger.info(f"Starting task {task.__class__.__name__} with priority {task.priority}")

          await task.run()
          self._collect_task_event(task)
          self.queue.remove(task)
          self.logger.info(f"Task {task.__class__.__name__} completed.")
        else:
          await asyncio.sleep(1)
      except Exception as e:
        error_stack = traceback.format_exc()
        self.logger.error(f"Stack trace:\n{error_stack}")
        self.logger.error(f"Queue Error: {e}")

        if self.queue:
          self.queue.sort(key=lambda t: t.priority)
          failed_task = self.queue[-1]
          self.queue.remove(failed_task)
          self._collect_task_event(failed_task)
          self.logger.warning(f"Removed failed task {failed_task.__class__.__name__} from queue.")
        else:
          self.logger.warning("Queue already empty after error; nothing to remove.")

        await asyncio.sleep(1)
