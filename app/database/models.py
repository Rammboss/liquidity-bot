from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database.database import Base


class IndexedStatus(Base):
  __tablename__ = "indexed_block"

  id: Mapped[int] = mapped_column(primary_key=True)
  latest_block: Mapped[int] = mapped_column(Integer, nullable=False)
  synced: Mapped[bool] = mapped_column(Boolean, nullable=False)


class MintEvent(Base):
  __tablename__ = "mint_events"

  id: Mapped[int] = mapped_column(primary_key=True)
  tx_hash: Mapped[str] = mapped_column(String(66), unique=True, nullable=False)
  token_id: Mapped[int] = mapped_column(Integer, nullable=True)
  liquidity: Mapped[int] = mapped_column(BigInteger, nullable=False)
  amount0: Mapped[int] = mapped_column(BigInteger, nullable=False)
  amount1: Mapped[int] = mapped_column(BigInteger, nullable=False)
  tick_lower: Mapped[int] = mapped_column(Integer, nullable=False)
  tick_upper: Mapped[int] = mapped_column(Integer, nullable=False)


class CollectEvent(Base):
  __tablename__ = "collect_events"

  id: Mapped[int] = mapped_column(primary_key=True)
  tx_hash: Mapped[str] = mapped_column(String(66), unique=True, nullable=False)
  token_id: Mapped[int] = mapped_column(Integer, nullable=True)
  amount0: Mapped[int] = mapped_column(BigInteger, nullable=False)
  amount1: Mapped[int] = mapped_column(BigInteger, nullable=False)

  # FK to Position
  position_id: Mapped[int] = mapped_column(Integer, ForeignKey("positions.id"), nullable=False)
  position: Mapped["Position"] = relationship("Position", back_populates="collect_events")


class Position(Base):
  __tablename__ = "positions"

  id: Mapped[int] = mapped_column(primary_key=True)

  token_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
  deposited_amount0: Mapped[int] = mapped_column(BigInteger, nullable=False)
  deposited_amount1: Mapped[int] = mapped_column(BigInteger, nullable=False)
  liquidity: Mapped[int] = mapped_column(BigInteger, nullable=False)
  tick_lower: Mapped[int] = mapped_column(Integer, nullable=False)
  tick_upper: Mapped[int] = mapped_column(Integer, nullable=False)
  is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)
  current_amount0: Mapped[int] = mapped_column(BigInteger, nullable=False)
  current_amount1: Mapped[int] = mapped_column(BigInteger, nullable=False)

  created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), insert_default=func.now(), nullable=False)
  updated_at: Mapped[datetime] = mapped_column(
    DateTime(timezone=True),
    server_default=func.now(),  # Set on Creation (DB side)
    onupdate=func.now(),  # Set on ORM Update (Python side)
    server_onupdate=func.now(),  # Set on any Update (DB side)
    nullable=False
  )

  # relationship to CollectEvent
  collect_events: Mapped[list["CollectEvent"]] = relationship(
    "CollectEvent",
    back_populates="position",
    cascade="all, delete-orphan"
  )
