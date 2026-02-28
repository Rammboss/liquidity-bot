import asyncio
import os
import time
from abc import ABC, abstractmethod
from threading import Thread
from typing import Literal, Tuple

import dotenv
from eth_account.datastructures import SignedTransaction
from eth_account.signers.local import LocalAccount
from web3 import AsyncWeb3, Web3, WebSocketProvider
from web3.middleware import ExtraDataToPOAMiddleware
from web3.types import TxParams, TxReceipt

from app.Configurations import DEFAULT_TIMEOUT_ORDERS
from app.blockchain.Contract import Contract
from blockchain.Token import Tokens
from logger import get_logger

ChainName = Literal[
  "ethereum",
  "arbitrum",
  "optimism",
  "unichain",
  "avalanche",
  "bsc",
  "base",
  "polygon",
  "blast",
  "worldchain"
]

dotenv.load_dotenv()


class IDEX(ABC):

  def __init__(self, name, chain: Literal[
    "ethereum",
    "ethereum_sepolia",
    "arbitrum",
    "optimism",
    "unichain",
    "avalanche",
    "bsc",
    "base",
    "polygon",
    "blast",
    "worldchain"
  ]
               ):
    self.logger = get_logger()
    self.name = name
    node_url = os.getenv(f"NODE_URL_{chain.upper()}")
    if not node_url:
      raise ValueError(f"No NODE_URL set for chain '{chain}'")

    node_url_ws = os.getenv(f"NODE_URL_{chain.upper()}_WS")
    if not node_url_ws:
      raise ValueError(f"No NODE_URL_WS set for chain '{chain}'")

    self.w3 = Web3(Web3.HTTPProvider(node_url))
    self.w3_ws = AsyncWeb3(WebSocketProvider(
      node_url_ws,
      websocket_kwargs={"ping_interval": 20, "ping_timeout": 10},
    ))

    self.chain_id = self.w3.eth.chain_id
    self.wallet: LocalAccount = self.w3.eth.account.from_key(os.getenv("PRIVATE_KEY"))

    self.universal_router = Contract.UNIVERSAL_ROUTER.get_contract(self.w3, self.chain_id)
    self.permit2 = Contract.PERMIT2.get_contract(self.w3, self.chain_id)

    self.eurc_contract = Contract.EURC.get_contract(self.w3, self.chain_id)
    self.usdc_contract = Contract.USDC.get_contract(self.w3, self.chain_id)
    self.usdc_decimals = self.eurc_contract.functions.decimals().call()
    self.eurc_decimals = self.eurc_contract.functions.decimals().call()
    if chain in {"bsc", "unichain", "polygon", "worldchain", "avalanche"}:
      self.w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    self.ticker = {
      'bid': 0.0,
      'bidVolume': 0.0,
      'ask': 0.0,
      'askVolume': 0.0,
      'timestamp': 0
    }
    self.ticker_thread: Thread = None

  def get_account_balances(self, token: Tokens, type: Literal["free", "total", "locked"]) -> float:
    match type:
      case "locked":
        return 0.0

    match token:
      case Tokens.ETH:
        balance_wei = self.w3.eth.get_balance(self.wallet.address)
        return float(self.w3.from_wei(balance_wei, "ether"))
      case Tokens.USDC:
        balance_raw = self.usdc_contract.functions.balanceOf(self.wallet.address).call()
        decimals = self.usdc_decimals
        return float(balance_raw / (10 ** decimals))
      case _:
        raise ValueError(f"Unsupported token: {token}")

  @abstractmethod
  async def create_order(
      self,
      side: str,
      type_: str,
      amount: float,
      price: float
  ):
    """Create a swap or liquidity order."""
    pass

  @abstractmethod
  async def prepare_order_tx(self, side: str, type_: str, amount: float, target_price: float) -> Tuple[
    float, TxParams
  ]:
    pass

  async def wait_tx_confirmed(self, tx_hash, confirmations=1, timeout=DEFAULT_TIMEOUT_ORDERS):
    start = time.time()

    while True:
      receipt: TxReceipt = self.w3.eth.get_transaction_receipt(tx_hash)

      if receipt:
        current_block = self.w3.eth.block_number

        # enough confirmations?
        if current_block - receipt.blockNumber >= confirmations:
          ok = receipt.status == 1
          self.logger.info(f"Tx {tx_hash} {'SUCCESS' if ok else 'FAILED'} (confirmed)")
          return ok  # True or False

      # timeout?
      if time.time() - start > timeout:
        self.logger.warning(f"Timeout waiting for tx {tx_hash}")
        return False

      await asyncio.sleep(1)

  def get_allowance(self, token_contract: Contract, owner: str, spender: str) -> int:
    """Return the ERC-20 allowance for (owner → spender)."""
    return token_contract.get_contract(self.w3, self.chain_id).functions.allowance(
      owner,
      spender
    ).call()

  def allowance_enough(self, token_contract: Contract, owner: str, spender: str, required_amount: int) -> bool:
    """Return True if allowance ≥ required_amount."""
    return required_amount < self.get_allowance(token_contract, owner, spender)

  async def approve_usdc_permit2(self, amount_sell: int = 2 ** 256 - 1):
    self.logger.info("Approve Universal Router to spend WETH...")
    tx = self.usdc_contract.functions.approve(
      Contract.PERMIT2.to_address(self.chain_id),
      amount_sell
    ).build_transaction({
      "from": self.wallet.address,
      "nonce": self.w3.eth.get_transaction_count(self.wallet.address),
    })

    estimated_gas = self.w3.eth.estimate_gas(tx)

    gas_costs = self.w3.from_wei((estimated_gas * self.w3.eth.gas_price), "ether")
    self.logger.info(f"Gas costs: {gas_costs:.18f} ETH - {float(gas_costs) * self.get_bid_ask()['ask']}")

    signed: SignedTransaction = self.wallet.sign_transaction(tx)
    tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
    self.logger.info(f"Approval tx sent: {tx_hash.hex()}")
