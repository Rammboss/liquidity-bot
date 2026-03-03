import telegram
from telegram.constants import ParseMode


class TelegramServices:
  def __init__(self, bot_token, chat_id):
    self.bot = telegram.Bot(token=bot_token)
    self.chat_id = chat_id
    self.last_update_id = 0

  async def native_send(self, msg: str, parse_mode: ParseMode | None = None):
    await self.bot.send_message(chat_id=self.chat_id, text=msg, parse_mode=parse_mode)

  async def send_message(
      self,
      tx1_0_symbol,
      tx1_0_amount,
      tx1_1_symbol,
      tx1_1_amount,
      tx2_0_symbol,
      tx2_0_amount,
      tx2_1_symbol,
      tx2_1_amount,
      tx1,
      victim_tx,
      tx_approval,
      tx2,
      profit
  ):
    pretty_text = (
      f"🔁 {tx1_0_amount:.2f} {tx1_0_symbol} → {tx1_1_amount:.2f} {tx1_1_symbol}\n"
      f"🔁 {tx2_0_amount:.2f} {tx2_0_symbol} → {tx2_1_amount:.2f} {tx2_1_symbol}\n"
      f"💰 Profit: {profit:.2f}"
    )
    await self.bot.send_message(chat_id=self.chat_id, text=pretty_text, parse_mode=ParseMode.HTML)

  async def mark_updates_as_seen(self):
    updates = await self.bot.get_updates(timeout=1)
    if not updates:
      return

    self.last_update_id = max(update.update_id for update in updates)

  async def get_latest_unseen_message(self) -> str | None:
    updates = await self.bot.get_updates(offset=self.last_update_id + 1, timeout=1)
    if not updates:
      return None

    latest_text = None
    latest_update_id = self.last_update_id
    expected_chat_id = str(self.chat_id)

    for update in updates:
      if update.update_id > latest_update_id:
        latest_update_id = update.update_id

      if not update.message or not update.message.text:
        continue

      if str(update.message.chat_id) != expected_chat_id:
        continue

      latest_text = update.message.text.strip()

    self.last_update_id = latest_update_id
    return latest_text
