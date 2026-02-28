from dataclasses import asdict
from enum import Enum
from typing import List, Union


class OrderSide(str, Enum):
  BUY = "BUY"
  SELL = "SELL"

  def __str__(self) -> str:
    return str(self.value)


class CoinbaseOrderTypes(str, Enum):
  MARKET_MARKET_IOC = "market_market_ioc"
  MARKET_MARKET_FOK = "market_market_fok"
  SOR_LIMIT_IOC = "sor_limit_ioc"
  LIMIT_LIMIT_GTC = "limit_limit_gtc"
  LIMIT_LIMIT_GTD = "limit_limit_gtd"
  LIMIT_LIMIT_FOK = "limit_limit_fok"
  TWAP_LIMIT_GTD = "twap_limit_gtd"
  STOP_LIMIT_STOP_LIMIT_GTC = "stop_limit_stop_limit_gtc"
  STOP_LIMIT_STOP_LIMIT_GTD = "stop_limit_stop_limit_gtd"
  TRIGGER_BRACKET_GTC = "trigger_bracket_gtc"
  TRIGGER_BRACKET_GTD = "trigger_bracket_gtd"
  SCALED_LIMIT_GTC = "scaled_limit_gtc"


from dataclasses import dataclass
from typing import Optional


@dataclass
class MarketMarketIoc:
  quote_size: str
  base_size: str


@dataclass
class MarketMarketFok:
  quote_size: str
  base_size: str


@dataclass
class SorLimitIoc:
  quote_size: str
  base_size: str
  limit_price: str


@dataclass
class LimitLimitGtc:
  base_size: Optional[str] = None
  quote_size: Optional[str] = None  # Keep optional, but only set one
  limit_price: str = "0.0"
  post_only: bool = False

  def to_dict(self):
    # Only include non-None values
    d = asdict(self)
    if self.base_size is not None and self.quote_size is not None:
      # Remove quote_size if base_size is set (oneof rule)
      d.pop("quote_size")
    return {k: v for k, v in d.items() if v is not None}


@dataclass
class LimitLimitGtd:
  quote_size: str
  base_size: str
  limit_price: str
  end_time: str
  post_only: bool


@dataclass
class LimitLimitFok:
  quote_size: str
  base_size: str
  limit_price: str


@dataclass
class TwapLimitGtd:
  quote_size: str
  base_size: str
  start_time: str
  end_time: str
  limit_price: str
  number_buckets: str
  bucket_size: str
  bucket_duration: str


@dataclass
class StopLimitStopLimitGtc:
  base_size: str
  limit_price: str
  stop_price: str
  stop_direction: str


@dataclass
class StopLimitStopLimitGtd:
  base_size: str
  limit_price: str
  stop_price: str
  end_time: str
  stop_direction: str


@dataclass
class TriggerBracketGtc:
  base_size: str
  limit_price: str
  stop_trigger_price: str


@dataclass
class TriggerBracketGtd:
  base_size: str
  limit_price: str
  stop_trigger_price: str
  end_time: str


@dataclass
class ScaledLimitGtcOrder:
  quote_size: str
  base_size: str
  limit_price: str
  post_only: bool


@dataclass
class ScaledLimitGtc:
  orders: List[ScaledLimitGtcOrder]
  quote_size: str
  base_size: str
  num_orders: int
  min_price: str
  max_price: str
  price_distribution: str
  size_distribution: str
  size_diff: str
  size_ratio: str


@dataclass
class OrderConfiguration:
  market_market_ioc: Optional[MarketMarketIoc] = None
  market_market_fok: Optional[MarketMarketFok] = None
  sor_limit_ioc: Optional[SorLimitIoc] = None
  limit_limit_gtc: Optional[LimitLimitGtc] = None
  limit_limit_gtd: Optional[LimitLimitGtd] = None
  limit_limit_fok: Optional[LimitLimitFok] = None
  twap_limit_gtd: Optional[TwapLimitGtd] = None
  stop_limit_stop_limit_gtc: Optional[StopLimitStopLimitGtc] = None
  stop_limit_stop_limit_gtd: Optional[StopLimitStopLimitGtd] = None
  trigger_bracket_gtc: Optional[TriggerBracketGtc] = None
  trigger_bracket_gtd: Optional[TriggerBracketGtd] = None
  scaled_limit_gtc: Optional[ScaledLimitGtc] = None

  @classmethod
  def from_type(cls, order_type: CoinbaseOrderTypes, config: Union[
    MarketMarketIoc,
    MarketMarketFok,
    SorLimitIoc,
    LimitLimitGtc,
    LimitLimitGtd,
    LimitLimitFok,
    TwapLimitGtd,
    StopLimitStopLimitGtc,
    StopLimitStopLimitGtd,
    TriggerBracketGtc,
    TriggerBracketGtd,
    ScaledLimitGtc
  ]
                ) -> "OrderConfiguration":
    """Factory to create the right configuration wrapper."""
    return cls(**{order_type.value: config})

  def to_dict(self) -> dict:
    """Convert to dict and filter out None values recursively."""

    def remove_none(d):
      if isinstance(d, dict):
        return {k: remove_none(v) for k, v in d.items() if v is not None}
      elif isinstance(d, list):
        return [remove_none(x) for x in d]
      else:
        return d

    return remove_none(asdict(self))


@dataclass
class CreateOrderRequest:
  client_order_id: str
  product_id: str
  side: OrderSide
  order_configuration: OrderConfiguration

  def to_payload(self) -> dict:
    """Convert dataclass to Coinbase API JSON body, skipping None values."""
    return {
      "client_order_id": self.client_order_id,
      "product_id": self.product_id,
      "side": self.side.value if isinstance(self.side, Enum) else self.side,
      "order_configuration": self.order_configuration.to_dict()
    }
