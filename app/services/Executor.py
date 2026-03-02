import asyncio
import traceback

from common.logger import get_logger
from execution.BasicTask import BasicTask


class Executor:
  def __init__(self):
    self.logger = get_logger()
    self.queue: list[BasicTask] = []

  async def run(self):
    while True:
      try:
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
        self.queue.pop()
        self.logger.warning(f"Remove job from queue.")
        await asyncio.sleep(1)
