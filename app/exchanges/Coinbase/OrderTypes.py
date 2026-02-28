from enum import StrEnum


class OrderTypes(StrEnum):
  LIMIT = "LIMIT"
  MARKET = "MARKET"

  def __str__(self) -> str:
    return str(self.value)
