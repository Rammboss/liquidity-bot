import asyncio

from common.TelegramServices import TelegramServices
from common.logger import get_logger
from services.RuntimeState import RuntimeState


class ControlService:
  def __init__(self, telegram: TelegramServices, runtime_state: RuntimeState):
    self.logger = get_logger()
    self.telegram = telegram
    self.runtime_state = runtime_state

  async def run(self):
    self.logger.info("Starting ControlService... Listening for #sleep and #start")
    await self.telegram.mark_updates_as_seen()

    while True:
      try:
        message = await self.telegram.get_latest_unseen_message()
        if not message:
          await asyncio.sleep(2)
          continue

        normalized = message.lower()

        if "#sleep" in normalized and not self.runtime_state.is_sleep_mode():
          self.runtime_state.set_sleep_mode(True)
          self.logger.warning("Sleep mode enabled by telegram command.")
          await self.telegram.native_send("😴 Sleep mode enabled (#sleep).")
        elif "#start" in normalized and self.runtime_state.is_sleep_mode():
          self.runtime_state.set_sleep_mode(False)
          self.logger.info("Sleep mode disabled by telegram command.")
          await self.telegram.native_send("🚀 Sleep mode disabled (#start).")

        await asyncio.sleep(1)
      except Exception as e:
        self.logger.error(f"ControlService error: {e}")
        await asyncio.sleep(2)
