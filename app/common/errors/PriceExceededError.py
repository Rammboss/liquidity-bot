from app.exchanges.Exchange import Exchange


class PriceExceededError(Exception):
  """Raised when ticker data is older than the allowed threshold."""

  def __init__(self, price: float, exchange: Exchange):
    super().__init__(f"Price exceeded: {price} on {exchange}")
    self.price = price
