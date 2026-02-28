from typing import Optional

from sqlalchemy.orm import Session

from postgres.Order import Order


class OrderRepository:
  def __init__(self, db_session: Session):
    self.db_session = db_session

  # Create / insert an order
  def add(self, order: Order):
    self.db_session.add(order)
    self.db_session.commit()
    self.db_session.refresh(order)
    return order

  # Read / get by primary key
  def get_by_id(self, order_id: str) -> Optional[Order]:
    return self.db_session.query(Order).filter_by(orderId=order_id).first()

  # Read all orders
  def get_all(self) -> list[type[Order]]:
    return self.db_session.query(Order).all()

  # Update an existing order
  def update(self, order: Order):
    self.db_session.commit()
    self.db_session.refresh(order)
    return order

  # Delete an order
  def delete(self, order: Order):
    self.db_session.delete(order)
    self.db_session.commit()
