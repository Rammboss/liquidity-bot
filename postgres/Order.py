from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import (Column, DateTime, Float, String)
from sqlalchemy import Enum as SAEnum

from app.exchanges.Coinbase.OrderTypes import OrderTypes
from app.exchanges.Coinbase.Requests.CreateOrderRequest import OrderSide
from app.exchanges.Exchange import Exchange
from postgres.services.DatabaseService import Base


class OrderStatus(StrEnum):
  CREATED = "CREATED"
  FAILED = "FAILED"
  FINISHED = "FINISHED"


class Order(Base):
  __tablename__ = "orders"

  order_id = Column(String, primary_key=True, index=True)
  pair = Column(String, nullable=False)
  side = Column(SAEnum(OrderSide), nullable=False)
  type = Column(SAEnum(OrderTypes), nullable=False)
  status = Column(SAEnum(OrderStatus), nullable=False)
  price = Column(Float, nullable=True)
  exchange = Column(SAEnum(Exchange), nullable=False)
  created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

  def __repr__(self):
    return (
      f"<Order("
      f"id='{self.order_id}', pair='{self.pair}', side='{self.side}', "
      f"type='{self.type}', status='{self.status}', price={self.price or 0}, created_at={self.created_at}"
      f")>"
    )
