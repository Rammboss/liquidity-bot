# cex_interface.py
from abc import ABC, abstractmethod
from threading import Thread
from typing import Dict, Literal, Optional

from app.exchanges.Exchange import Exchange
from blockchain.Token import Tokens


class ICEX(ABC):

  def __init__(self, name: Exchange):
    self.name = name
    self.cctx = None
    self.ticker = {
      'bid': 0.0,
      'bidVolume': 0.0,
      'ask': 0.0,
      'askVolume': 0.0,
      'timestamp': 0
    }
    self.ticker_thread: Thread = None

  @abstractmethod
  async def init(self):
    pass

  # @abstractmethod
  # def _start_ticker(self):
  #   pass
  #
  # @abstractmethod
  # def get_bid_ask(self) -> Dict[str, float]:
  #   """Return the latest bid/ask prices."""
  #   pass

  def get_account_balances(self, token: Tokens, type: Literal["free", "total", "locked"]):
    balances = self.cctx.fetch_balance()
    token_str = token.to_string()
    return balances.get(token_str, {}).get(type, 0.0)

  @abstractmethod
  def create_order(
      self,
      side: str,
      type: str,
      amount: float,
      price: Optional[float] = None
  ):
    """Create an order."""
    pass

  @abstractmethod
  async def cancel_order(self, order_id: str):
    """Cancel an order."""
    pass

  @abstractmethod
  async def wait_order_filled(self, order_id: str, timeout: int = 30):
    """Wait until the order is filled or timeout occurs."""
    pass

  @abstractmethod
  def get_trade_fee(self):
    pass
