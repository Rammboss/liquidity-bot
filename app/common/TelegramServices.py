import telegram
from telegram.constants import ParseMode
from web3 import Web3


class TelegramServices:
  def __init__(self, bot_token, chat_id):
    self.bot = telegram.Bot(token=bot_token)
    self.chat_id = chat_id

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
    pretty_text = f"""
I. Swap {tx1_0_amount} {tx1_0_symbol} ➡️ {tx1_1_amount} {tx1_1_symbol}\n
II. Swap {tx2_0_amount} {tx2_0_symbol} ➡️ {tx2_1_amount} {tx2_1_symbol}\n
Profit: {profit}💲\n                                   
"""
    await self.bot.send_message(chat_id=self.chat_id, text=pretty_text, parse_mode=ParseMode.HTML)
