import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Literal, Optional

import dotenv
import requests
from coinbase import jwt_generator
from coinbase.rest import RESTClient
from coinbase.rest.types.orders_types import GetOrderResponse
from coinbase.rest.types.product_types import GetProductBookResponse, ListProductsResponse, Product
from web3 import Web3

from app.Configurations import DEFAULT_TIMEOUT_ORDERS
from app.exchanges.Coinbase.DepositAdresses import DepositAddresses
from app.exchanges.Coinbase.Responses.TransactionList import Transaction, TransactionList
from app.exchanges.Exchange import Exchange
from app.exchanges.ICEX import ICEX
from blockchain.Network import Network
from blockchain.Token import Token, Tokens
from common.logger import get_logger

dotenv.load_dotenv()


class Coinbase(ICEX):
  def __init__(self, symbol: str, token0: Tokens, token1: Tokens):
    super().__init__(Exchange.COINBASE)
    self.logger = get_logger()
    self.symbol = symbol

    self.api_key = os.getenv("COINBASE_API_KEY")
    self.api_secret = os.getenv("COINBASE_API_SECRET")
    self.base_url = "https://api.exchange.coinbase.com"
    self.url_coinbase_advanced_trade_api = "https://api.coinbase.com"
    self.url_coinbase_exchange_api = "https://api.exchange.coinbase.com"

    if not self.api_key or not self.api_secret:
      raise EnvironmentError("Missing Coinbase API credentials")

    self._last_fee_update: datetime = datetime.now() - timedelta(hours=1)
    self._cached_fee: Optional[dict] = None
    self.product = self.get_product_id(token0, token1)

    self.w3 = Web3(Web3.HTTPProvider(os.getenv("RPC_URL")))

  def _generate_jwt(self, request_method: str, request_path: str) -> str:
    """Generate JWT for Coinbase API authentication."""
    jwt_uri = jwt_generator.format_jwt_uri(request_method, request_path)
    return jwt_generator.build_rest_jwt(jwt_uri, self.api_key, self.api_secret.replace("\\n", "\n"))

  async def init(self):
    self.logger.info("Coinbase client initialized")

  def _advanced_trade_request(self, method: str, path: str, params: Optional[dict] = None,
                              payload: Optional[dict] = None
                              ) -> dict:
    jwt_token = self._generate_jwt(method, path)
    url = f"{self.url_coinbase_advanced_trade_api}{path}"
    response = requests.request(
      method=method,
      url=url,
      headers={"Authorization": f"Bearer {jwt_token}", "Content-Type": "application/json"},
      params=params,
      json=payload,
      timeout=20,
    )
    response.raise_for_status()
    return response.json() if response.content else {}

  def create_order(self, token0: Tokens, token1: Tokens, side: str, type_: str, amount: float, price: Optional[float] = None):
    side = side.lower()
    type_ = type_.lower()
    if side not in ('buy', 'sell') or type_ not in ('limit', 'market'):
      raise ValueError("Invalid side or type")

    if type_ == "limit" and price is None:
      raise ValueError("price is required for limit orders")

    order_configuration: dict
    if type_ == "market":
      market_config = {"base_size": str(amount)}
      if side == "buy":
        market_config = {"quote_size": str(amount)}
      order_configuration = {"market_market_ioc": market_config}
    else:
      base_size = amount / price if side == "buy" else amount
      order_configuration = {
        "limit_limit_gtc": {
          "base_size": str(base_size),
          "limit_price": str(price),
          "post_only": False,
        }
      }

    payload = {
      "client_order_id": str(uuid.uuid4()),
      "product_id": self.get_product_id(token0, token1).product_id,
      "side": side.upper(),
      "order_configuration": order_configuration,
    }
    response = self._advanced_trade_request("POST", "/api/v3/brokerage/orders", payload=payload)
    order_id = response.get("success_response", {}).get("order_id")
    order = {"id": order_id, "status": "open", "raw": response}
    self.logger.info(f"Order created: {order_id if order_id else 'None'}")
    return order

  def get_eth_price(self):
    ticker = self._advanced_trade_request("GET", "/api/v3/brokerage/products/ETH-USD/ticker")
    trades = ticker.get("trades", [])
    if trades:
      return float(trades[0]["price"])
    pricebook = ticker.get("pricebook", {})
    bids = pricebook.get("bids", [])
    if bids:
      return float(bids[0]["price"])
    raise RuntimeError("Unable to determine ETH price from Coinbase ticker response")

  def cancel_order(self, order_id: str):
    try:
      order = self._advanced_trade_request(
        "POST",
        "/api/v3/brokerage/orders/batch_cancel",
        payload={"order_ids": [order_id]},
      )
      self.logger.info(f"Order canceled: {order_id}")
      return order
    except requests.RequestException as e:
      self.logger.error(f"Error canceling order {order_id}: {e}", exc_info=True)
      return None

  async def wait_order_filled(self, order_id: str, timeout: int = DEFAULT_TIMEOUT_ORDERS):
    end_time = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end_time:
      order_response = self._advanced_trade_request("GET", f"/api/v3/brokerage/orders/historical/{order_id}")
      order = order_response.get("order", {})
      status = order.get("status", "").lower()
      if status in ('filled', 'cancelled', 'canceled'):
        self.logger.info(f"Order {order_id} filled with status: {status}")
        return {"id": order_id, "status": status, "raw": order_response}
      await asyncio.sleep(0.5)
    self.logger.warning(f"Timeout waiting for order {order_id} to fill")
    return None

  def get_trade_fee(self):
    now = datetime.now()
    if self._cached_fee is None or now - self._last_fee_update >= timedelta(minutes=30):
      fee_response = self._advanced_trade_request("GET", "/api/v3/brokerage/transaction_summary")
      self._cached_fee = {
        "maker": float(fee_response.get("fee_tier", {}).get("maker_fee_rate", 0.0)),
        "taker": float(fee_response.get("fee_tier", {}).get("taker_fee_rate", 0.0)),
        "raw": fee_response,
      }
      self._last_fee_update = now

    return self._cached_fee

  def get_account_balances(self, token: Tokens, type: Literal["free", "total", "locked"]):
    accounts_response = self._advanced_trade_request("GET", "/api/v3/brokerage/accounts")
    for account in accounts_response.get("accounts", []):
      if account.get("currency") != token.to_string():
        continue

      available = float(account.get("available_balance", {}).get("value", 0.0))
      hold = float(account.get("hold", {}).get("value", 0.0))
      match type:
        case "free":
          return available
        case "locked":
          return hold
        case "total":
          return available + hold

    return 0.0

  async def estimate_withdrawal_fees(self) -> float:
    """Return hardcoded withdrawal fees for a given token."""
    gas_price_gwei = self.w3.eth.gas_price / 1e9
    gas_limit = 65000
    fee_eth = gas_price_gwei * gas_limit / 1e9
    fee_usd = fee_eth * self.get_eth_price()
    return max(fee_usd * 2 + 0.01, 0.11)  # Ensure a minimum fee of $0.11

  def get_deposit_addresses(self, currency: Tokens, network: Network) -> str | None:
    """List withdrawal addresses for a given currency."""

    account_uuid = self.get_account_uuid(currency)

    jwt_token = self._generate_jwt("GET", f"/v2/accounts/{account_uuid}/addresses")

    url = f"{self.url_coinbase_advanced_trade_api}/v2/accounts/{account_uuid}/addresses"

    response = requests.get(url, headers={"Authorization": f"Bearer {jwt_token}"})
    data = response.json()["data"]

    if not data:
      return None

    # Sort by created_at descending and return the first address
    # latest_address = sorted(data, key=lambda x: x["created_at"], reverse=True)[0]["address"]

    deposit_addresses = DepositAddresses(token=currency)

    # Temporary dict to keep track of the newest address per network
    newest_per_network: dict[str, dict] = {}

    for entry in data:
      network_name = entry["network"]
      created_at = entry["created_at"]

      # If network not seen yet or this entry is newer, update it
      if network_name not in newest_per_network or created_at > newest_per_network[network_name]["created_at"]:
        newest_per_network[network_name] = entry

    # Map Network enum to address
    for network_name, entry in newest_per_network.items():
      try:
        network_enum = Network.from_string(network_name)
        if network_enum is Network.ETH:
          deposit_addresses.add_network_address(Network.BASE, entry["address"])
          deposit_addresses.add_network_address(Network.ARBITRUM, entry["address"])
          deposit_addresses.add_network_address(Network.POLYGON, entry["address"])
          deposit_addresses.add_network_address(Network.OPTIMISM, entry["address"])
        deposit_addresses.add_network_address(network_enum, entry["address"])
      except KeyError:
        # Skip networks that aren't in your Network enum
        continue
    return deposit_addresses.get_address(network)

  def get_product_id(self, token0: Tokens, token1: Tokens) -> Product:
    client = RESTClient(api_key=self.api_key, api_secret=self.api_secret)

    products_response: ListProductsResponse = client.get_products()

    # Iterate over all products
    for p in products_response.products:
      # Match base and quote currencies in either order
      if ((p.base_currency_id == token0.value and p.quote_currency_id == token1.value) or
          (p.base_currency_id == token1.value and p.quote_currency_id == token0.value)):
        return p

    # If no product matches, raise an error
    raise ValueError(f"No product found for tokens: {token0} / {token1}")

  def order_filled(self, order) -> bool:
    client = RESTClient(api_key=self.api_key, api_secret=self.api_secret)

    order: GetOrderResponse = client.get_order(order_id=order.order_id)

    return order.order.status == "FILLED"

  def get_account_uuid(self, currency: Tokens) -> str:
    """Fetch the account UUID for a given currency."""
    client = RESTClient(api_key=self.api_key, api_secret=self.api_secret)
    accounts = client.get_accounts()["accounts"]

    for acc in accounts:
      match acc["name"]:
        case curr if curr == f"{currency.name} Wallet":
          return acc["uuid"]

    raise ValueError(f"Account UUID not found for currency: {currency.name}")

  def get_orders(self):
    jwt_token = self._generate_jwt("GET", "/api/v3/brokerage/orders/historical/batch")

    url = f"{self.url_coinbase_advanced_trade_api}/api/v3/brokerage/orders/historical/batch"

    response = requests.get(url, headers={"Authorization": f"Bearer {jwt_token}"})
    return json.loads(response.text)

  def get_product_book(self, product_id, limit=None, aggregation_price_increment=None) -> GetProductBookResponse:
    client = RESTClient(api_key=self.api_key, api_secret=self.api_secret)

    return client.get_product_book(product_id=product_id, level=2, limit=limit,
                                   aggregation_price_increment=aggregation_price_increment)

  def withdrawal(self, token: Tokens, dest_address: str, amount: float, network: Network) -> dict:
    """Initiate a withdrawal and return the transaction ID"""
    account_uuid = self.get_account_uuid(token)

    jwt_token = self._generate_jwt("POST", f"/v2/accounts/{account_uuid}/transactions")
    url = f"{self.url_coinbase_advanced_trade_api}/v2/accounts/{account_uuid}/transactions"
    # Required request body
    payload = {
      "type": "send",  # ✅ Required
      "to": dest_address,  # ✅ Required — blockchain address or email
      "amount": str(amount),  # ✅ Required — must be string
      "currency": token.to_string(),
      "network": network.to_string(),
      "travel_rule_data": {
        "beneficiary_wallet_type": "WALLET_TYPE_SELF_HOSTED",
        "is_self": "IS_SELF_TRUE",
        "beneficiary_name": "Thomas Lippert",
        "beneficiary_address": {
          "address1": "Wilhelm-Liebknecht-Str. 54",
          "city": "Giessen",
          "state": "DE",
          "postal_code": "35396",
          "country": "DE"
        },
        "transfer_purpose": "automatic wallet transfer"

      }  # ✅ Required SELF_HOSTED for crypto withdrawals
      # "travel_rule_data": {
      #     "beneficiary_wallet_type": "WALLET_TYPE_EXCHANGE",
      #     "beneficiary_financial_institution": "f154f695-af70-4c96-814b-c6cc308b9b0f"
      # }  # ✅ Required EXCHANGE for exchange withdrawals
    }  # TODO: PROD

    # Optional but recommended for idempotence
    payload["idem"] = str(uuid.uuid4())

    # Send POST request
    response = requests.post(
      url,
      headers={
        "Authorization": f"Bearer {jwt_token}",
        "Content-Type": "application/json",
      },
      json=payload,
    )

    # Raise error if something went wrong
    response.raise_for_status()

    return response.json()

  def v2_list_transactions(self, token: Tokens) -> TransactionList:
    """List transactions using Coinbase V2 API."""
    account_uuid = self.get_account_uuid(token)

    jwt_token = self._generate_jwt("GET", f"/v2/accounts/{account_uuid}/transactions")
    url = f"{self.url_coinbase_advanced_trade_api}/v2/accounts/{account_uuid}/transactions"
    # Send POST request
    response = requests.get(
      url,
      headers={"Authorization": f"Bearer {jwt_token}"}
    )

    # Raise error if something went wrong
    response.raise_for_status()

    tx_list = TransactionList.from_list(response.json().get("data", []))

    # Access
    for tx in tx_list.transactions:
      print(f"{tx.created_at} | {tx.type} | {tx.amount.amount} {tx.amount.currency}")
      if tx.network:
        print(f"  → Network: {tx.network.network_name} ({tx.network.status})")
      if tx.advanced_trade_fill:
        print(f"  → Trade: {tx.advanced_trade_fill.product_id} at {tx.advanced_trade_fill.fill_price}")
    return tx_list

  def v2_list_transaction(self, token: Tokens, transaction_id: str) -> Transaction:
    """Get a single transaction using Coinbase V2 API."""
    account_uuid = self.get_account_uuid(token)

    jwt_token = self._generate_jwt("GET", f"/v2/accounts/{account_uuid}/transactions/{transaction_id}")
    url = f"{self.url_coinbase_advanced_trade_api}/v2/accounts/{account_uuid}/transactions/{transaction_id}"
    # Send POST request
    response = requests.get(
      url,
      headers={"Authorization": f"Bearer {jwt_token}"}
    )

    # Raise error if something went wrong
    response.raise_for_status()

    tx = Transaction.from_dict(response.json().get("data"))

    return tx

  def list_transactions(self, token: Tokens, tx_id: str):
    account_uuid = self.get_account_uuid(token)

    jwt_token = self._generate_jwt("GET", f"/v2/accounts/{account_uuid}/transactions")
    url = f"{self.url_coinbase_advanced_trade_api}/v2/accounts/{account_uuid}/transactions"
    # Send POST request
    response = requests.get(
      url,
      headers={"Authorization": f"Bearer {jwt_token}"}
    )

    # Raise error if something went wrong
    response.raise_for_status()

    tx = Transaction.from_dict(response.json().get("data"))

    return tx

  async def wait_till_withdrawal_confirmed(self, token: Tokens, tx_id: str, timeout: int = DEFAULT_TIMEOUT_ORDERS):
    end_time = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end_time:
      tx = self.v2_list_transaction(token, tx_id)
      if tx.status == "completed":
        self.logger.info(f"Withdrawal {tx_id} confirmed on network {tx.network.network_name}")
        return True
      await asyncio.sleep(1)
    self.logger.warning(f"Timeout waiting for withdrawal {tx_id} to be confirmed")
    return False

  async def wait_till_deposit_arrives(self, send_token: Token, timeout: int = DEFAULT_TIMEOUT_ORDERS):
    end_time = asyncio.get_event_loop().time() + timeout

    balance_before = float(self.get_account_balances(send_token.token, "free"))
    self.logger.info(f"Waiting for {send_token.token} deposit. Starting balance: {balance_before}")

    while asyncio.get_event_loop().time() < end_time:
      try:
        balance_after = float(self.get_account_balances(send_token.token, "free"))

        if balance_after > balance_before:
          diff = balance_after - balance_before
          self.logger.info(f"Deposit detected! Balance increased by {diff} {send_token.token}")
          return True

      except Exception as e:
        self.logger.error(f"Error checking balance: {e}")

      await asyncio.sleep(3)

    self.logger.warning(f"Timeout reached after {timeout}s waiting for {send_token.token} deposit.")
    return False
