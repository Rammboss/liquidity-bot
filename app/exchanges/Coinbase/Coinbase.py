import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Optional

import ccxt
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
from blockchain.Token import Tokens
from logger import get_logger

dotenv.load_dotenv()


class Coinbase(ICEX):
  def __init__(self, symbol: str, token0: Tokens, token1: Tokens):
    super().__init__(Exchange.COINBASE)
    self.logger = get_logger()
    self.symbol = symbol

    api_key: str = os.getenv("COINBASE_API_KEY") or (_ for _ in ()).throw(RuntimeError("COINBASE_API_KEY must be set"))
    secret: str = os.getenv("COINBASE_API_SECRET").replace('\\n', '\n') or (_ for _ in ()).throw(
      RuntimeError("COINBASE_API_SECRET must be set"))

    self.cctx = ccxt.coinbaseadvanced(
      {
        'apiKey': api_key,
        'secret': secret,
        'enableRateLimit': True,
        'options': {'defaultType': 'spot'},
      }
    )

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
    self.logger.info("Loading markets...")
    self.cctx.load_markets()

  def create_order(self, side: str, type_: str, amount: float, price: Optional[float] = None):
    side = side.lower()
    type_ = type_.lower()
    if side not in ('buy', 'sell') or type_ not in ('limit', 'market'):
      raise ValueError("Invalid side or type")
    params = {'postOnly': False} if type_ == 'limit' else {}
    amount_to_use = amount / price if side.lower() == "buy" else amount
    order = self.cctx.create_order(self.symbol, type_, side, amount_to_use, price, params)
    self.logger.info(f"Order created: {order['id'] if order else 'None'}")
    return order

  def get_eth_price(self):
    ticker = self.cctx.fetch_ticker('ETH-USD')
    return ticker['bid']

  def cancel_order(self, order_id: str):
    try:
      order = self.cctx.cancel_order(order_id, self.symbol)
      self.logger.info(f"Order canceled: {order_id}")
      return order
    except ccxt.BaseError as e:
      self.logger.error(f"Error canceling order {order_id}: {e}", exc_info=True)
      return None

  async def wait_order_filled(self, order_id: str, timeout: int = DEFAULT_TIMEOUT_ORDERS):
    end_time = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end_time:
      order = self.cctx.fetch_order(order_id, self.symbol)
      if order['status'] in ('closed', 'canceled', 'filled'):
        self.logger.info(f"Order {order_id} filled with status: {order['status']}")
        return order
      await asyncio.sleep(0.5)
    self.logger.warning(f"Timeout waiting for order {order_id} to fill")
    return None

  def get_trade_fee(self):
    now = datetime.now()
    if self._cached_fee is None or now - self._last_fee_update >= timedelta(minutes=30):
      self._cached_fee = self.cctx.fetch_trading_fee(self.symbol)
      self._last_fee_update = now

    return self._cached_fee

  async def get_withdrawal_fees(self) -> float:
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
