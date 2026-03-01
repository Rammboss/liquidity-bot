import asyncio

from common.logger import get_logger
from execution.BasicTask import BasicTask


class Executor:
  def __init__(self):
    self.logger = get_logger()
    self.queue: list[BasicTask] = []

  async def run(self):
    while True:
      try:
        if len(self.queue) > 0:
          # 1. Sortieren nach Priorität (Höchste zuerst)
          self.queue.sort(key=lambda t: t.priority, reverse=True)
          task = self.queue[0]
          self.logger.info(f"Starting task {task.__class__.__name__} with priority {task.priority}")
          try:
            await task.run()
            if task in self.queue:
              self.queue.pop()
              self.logger.info(f"Task {task.__class__.__name__} successfully completed and popped.")
          except Exception as e:
            self.queue.pop()
            self.logger.error(f"Task {task.__class__.__name__} failed: {e}. Keeping in queue for retry.")
        else:
          await asyncio.sleep(1)
      except Exception as e:
        self.logger.error(f"Error executing task: {e}")
        await asyncio.sleep(30)
