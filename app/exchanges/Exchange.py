from enum import StrEnum


class Exchange(StrEnum):
  BINANCE = "binance"
  COINBASE = "coinbase"
  KUCOIN = "kucoin"
  OKX = "OKX"
  BYBIT = "bybit"

  def to_string(self) -> str:
    """Return the string value of the exchange name."""
    return str(self.value)
