from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class CurrencyAmount:
  amount: str
  currency: str


@dataclass
class NetworkTransactionFee:
  amount: str
  currency: str


@dataclass
class NetworkInfo:
  hash: Optional[str] = None
  network_name: Optional[str] = None
  status: Optional[str] = None
  transaction_fee: Optional[NetworkTransactionFee] = None


@dataclass
class ToAddress:
  address: Optional[str] = None
  resource: Optional[str] = None


@dataclass
class AdvancedTradeFill:
  commission: Optional[str] = None
  fill_price: Optional[str] = None
  order_id: Optional[str] = None
  order_side: Optional[str] = None
  product_id: Optional[str] = None


@dataclass
class Transaction:
  id: str
  type: str
  status: str
  created_at: datetime
  amount: CurrencyAmount
  native_amount: CurrencyAmount
  resource: str
  resource_path: str

  idem: Optional[str] = None
  network: Optional[NetworkInfo] = None
  to: Optional[ToAddress] = None
  advanced_trade_fill: Optional[AdvancedTradeFill] = None

  @staticmethod
  def from_dict(data: dict) -> "Transaction":
    """Convert a single transaction dict to a Transaction object."""
    return Transaction(
      id=data["id"],
      type=data.get("type"),
      status=data.get("status"),
      created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
      amount=CurrencyAmount(**data["amount"]),
      native_amount=CurrencyAmount(**data["native_amount"]),
      resource=data.get("resource"),
      resource_path=data.get("resource_path"),
      idem=data.get("idem"),
      network=NetworkInfo(
        hash=data["network"].get("hash"),
        network_name=data["network"].get("network_name"),
        status=data["network"].get("status"),
        transaction_fee=NetworkTransactionFee(**data["network"]["transaction_fee"])
        if "network" in data and data["network"].get("transaction_fee")
        else None,
      )
      if "network" in data
      else None,
      to=ToAddress(**data["to"]) if "to" in data else None,
      advanced_trade_fill=AdvancedTradeFill(**data["advanced_trade_fill"])
      if "advanced_trade_fill" in data
      else None,
    )


@dataclass
class TransactionList:
  transactions: List[Transaction] = field(default_factory=list)

  @staticmethod
  def from_list(data: list[dict]) -> "TransactionList":
    """Convert the full response list into a TransactionList."""
    return TransactionList([Transaction.from_dict(tx) for tx in data])
