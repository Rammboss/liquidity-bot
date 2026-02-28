from sqlalchemy.orm import Session

from database.models import CollectEvent, IndexedStatus, MintEvent, Position
from logger import get_logger


class IndexedBlockRepository:
  def __init__(self, db: Session):
    self.db = db

  def get_latest(self) -> IndexedStatus:
    row = self.db.query(IndexedStatus).order_by(IndexedStatus.id.desc()).first()
    if row is None:
      row = IndexedStatus(latest_block=0, synced=False)
      self.db.add(row)
      self.db.commit()
    return row

  def set_latest(self, block_number: int) -> None:
    row = self.db.query(IndexedStatus).first()
    if row:
      row.latest_block = block_number
    else:
      row = IndexedStatus(latest_block=block_number, synced=False)
      self.db.add(row)
    self.db.commit()


class MintEventsRepository:
  def __init__(self, db: Session):
    self.logger = get_logger()
    self.db = db

  def save_event(self, tx_hash: str, token_id: int, liquidity: str, amount0: str, amount1: int, tick_lower: int,
                 tick_upper: int
                 ):
    if self.db.query(MintEvent).filter_by(tx_hash=tx_hash).first():
      self.logger.info(f"Event with tx_hash {tx_hash} already exists, skipping.")
      return
    event = MintEvent(
      tx_hash=tx_hash,
      token_id=token_id,
      liquidity=liquidity,
      amount0=amount0,
      amount1=amount1,
      tick_lower=tick_lower,
      tick_upper=tick_upper
    )
    self.db.add(event)
    self.db.commit()


class CollectEventsRepository:
  def __init__(self, db: Session):
    self.logger = get_logger()
    self.db = db

  def save(self, tx_hash: str, token_id: int, amount0: str, amount1: int, position_id: int):
    if self.db.query(CollectEvent).filter_by(tx_hash=tx_hash).first():
      self.logger.info(f"Event with tx_hash {tx_hash} already exists, skipping.")
      return

    event = CollectEvent(
      tx_hash=tx_hash,
      token_id=token_id,
      amount0=amount0,
      amount1=amount1,
      position_id=position_id
    )
    self.db.add(event)
    self.db.commit()


class PositionRepository:
  def __init__(self, db: Session):
    self.db = db
    self.logger = get_logger()

  def save(self, position: Position):
    """
    Saves or updates a position.
    Uses merge() to handle both existing and new records efficiently.
    """
    position = self.db.merge(position)
    self.db.commit()
    return position

  def get_active_positions(self) -> list[type[Position]]:
    return self.db.query(Position).filter_by(is_active=True).all()

  def get_active_by_token_id(self, token_id: int) -> Position | None:
    return self.db.query(Position).filter_by(is_active=True, token_id=token_id).first()

  def get_by_token_id(self, token_id: int) -> Position | None:
    return self.db.query(Position).filter_by(token_id=token_id).first()
