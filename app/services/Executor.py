import asyncio
import traceback

from common.logger import get_logger
from execution.BasicTask import BasicTask


class Executor:
  def __init__(self, runtime_state=None):
    self.logger = get_logger()
    self.runtime_state = runtime_state
    self.queue: list[BasicTask] = []

  def clear_queue(self):
    if self.queue:
      self.logger.warning(f"Clearing executor queue with {len(self.queue)} pending task(s).")
    self.queue.clear()

  async def run(self):
    # Ensure executor starts from a clean queue.
    self.clear_queue()

    while True:
      try:
        if self.runtime_state and self.runtime_state.is_sleep_mode():
          await asyncio.sleep(1)
          continue

        if self.queue:
          # Sort ascending: highest priority moves to the end of the list
          self.queue.sort(key=lambda t: t.priority)

          # Get the last item (highest priority)
          task = self.queue[-1]
          self.logger.info(f"Starting task {task.__class__.__name__} with priority {task.priority}")

          await task.run()
          self.queue.pop()
          self.logger.info(f"Task {task.__class__.__name__} completed.")
        else:
          await asyncio.sleep(1)
      except Exception as e:
        error_stack = traceback.format_exc()
        self.logger.error(f"Stack trace:\n{error_stack}")
        self.logger.error(f"Queue Error: {e}")

        if self.queue:
          failed_task = self.queue.pop()
          self.logger.warning(f"Removed failed task {failed_task.__class__.__name__} from queue.")
        else:
          self.logger.warning("Queue already empty after error; nothing to remove.")

        await asyncio.sleep(1)
