import asyncio
from datetime import datetime, timedelta, timezone

from common.TelegramServices import TelegramServices
from common.logger import get_logger
from services.RuntimeState import RuntimeState


class ControlService:
  REPORT_INTERVAL_SECONDS = 300

  def __init__(self, telegram: TelegramServices, runtime_state: RuntimeState):
    self.logger = get_logger()
    self.telegram = telegram
    self.runtime_state = runtime_state
    self._last_task_report_at: datetime | None = None

  async def run(self):
    self.logger.info("Starting ControlService... Listening for #sleep and #start")
    await self.telegram.mark_updates_as_seen()

    while True:
      try:
        await self._report_tasks_if_due()

        message = await self.telegram.get_latest_unseen_message()
        if not message:
          await asyncio.sleep(2)
          continue

        normalized = message.lower()

        if "#sleep" in normalized and not self.runtime_state.is_sleep_mode():
          self.runtime_state.set_sleep_mode(True)
          self.logger.warning("Sleep mode enabled by telegram command.")
          await self.telegram.native_send("😴 Sleep mode: ON. Use #start to resume.", force=True)
        elif "#start" in normalized and self.runtime_state.is_sleep_mode():
          self.runtime_state.set_sleep_mode(False)
          self.logger.info("Sleep mode disabled by telegram command.")
          await self.telegram.native_send("🚀 Sleep mode: OFF. Trading resumed.", force=True)

        await asyncio.sleep(1)
      except Exception as e:
        self.logger.error(f"ControlService error: {e}")
        await asyncio.sleep(2)

  async def _report_tasks_if_due(self) -> None:
    now = datetime.now(timezone.utc)
    if self._last_task_report_at and now - self._last_task_report_at < timedelta(seconds=self.REPORT_INTERVAL_SECONDS):
      return

    task_snapshot = self.runtime_state.get_task_snapshot()
    if task_snapshot:
      self.logger.info(f"Task snapshot ({len(task_snapshot)}): {', '.join(task_snapshot)}")
    else:
      self.logger.info("Task snapshot: queue empty")

    task_events = self.runtime_state.pop_task_events()
    if task_events:
      self.logger.info(f"Sending bundled task report with {len(task_events)} event(s) to Telegram.")
      message = "🧾 Task Report (5m)\n" + "\n".join(f"{idx}. {event}" for idx, event in enumerate(task_events, start=1))
      await self.telegram.native_send(message)
    else:
      self.logger.info("Skip Telegram task report: no new task events.")

    self._last_task_report_at = now
