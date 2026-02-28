from datetime import datetime

from coinbase.rest.types.orders_types import CreateOrderResponse

from Binance.responses.BinanceOrderResponse import BinanceOrderResponse, OrderStatus
from Coinbase.Requests.CreateOrderRequest import OrderSide
from Exchanges.Exchange import Exchange
from postgres.Order import Order


class OrderMapper:
  """Maps external exchange order responses (Binance, Coinbase, etc.) into unified Order entities."""

  @staticmethod
  def from_binance_response(resp: BinanceOrderResponse, exchange: Exchange) -> Order:
    """Convert a Binance order response into an internal Order model."""
    return Order(
      order_id=str(resp.orderId),
      pair=resp.symbol,
      side=str(resp.side),
      type=str(resp.type),
      status=str(resp.status),
      price=float(resp.price),
      exchange=exchange,
      created_at=datetime.fromtimestamp(resp.transactTime / 1000) if getattr(resp, "transactTime", None) else None,
    )

  @staticmethod
  def from_coinbase_response(resp: CreateOrderResponse, type: str, order_side: OrderSide, status: OrderStatus,
                             exchange: Exchange
                             ) -> Order:
    """Convert a Coinbase order response into an internal Order model."""
    return Order(
      order_id=resp.success_response['order_id'],
      pair=resp.success_response['product_id'],
      side=order_side,
      type=type,
      status=status,
      exchange=exchange
    )
