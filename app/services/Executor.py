import asyncio

from execution.BasicTask import BasicTask
from common.logger import get_logger


class Executor:
  def __init__(self):
    self.logger = get_logger()
    self.queue: list[BasicTask] = []

  async def run(self):
    while True:
      try:
        if len(self.queue) > 0:
          self.queue.sort(
            key=lambda t: t.priority,
            reverse=True
          )
          task = self.queue.pop(0)
          self.logger.info(f"Executing task {task.__class__.__name__} with priority {task.priority}")
          await task.run()
      except Exception as e:
        self.logger.error(f"Error executing task: {e}")
        await asyncio.sleep(5)


