import asyncio
import os
import time

import dotenv
from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_typing import Hash32, HexStr
from hexbytes import HexBytes
from web3 import Web3

from Configurations import DEFAULT_TIMEOUT_ORDERS
from blockchain.Token import Token
from common.logger import get_logger

dotenv.load_dotenv()


class WalletService:
  def __init__(self):
    self.logger = get_logger()
    self.w3 = Web3(Web3.HTTPProvider(os.getenv("RPC_URL")))
    self.wallet: LocalAccount = Account.from_key(os.getenv("PRIVATE_KEY"))

  async def get_transfer_costs(self, token: Token, eth_price: float) -> float:
    tx = token.contract.functions.transfer(
      self.wallet.address,
      1
    ).build_transaction({
      "from": self.wallet.address,
      "nonce": self.w3.eth.get_transaction_count(self.wallet.address),
    })
    gas = self.w3.eth.estimate_gas(tx)
    gas_price_wei = tx.get("maxFeePerGas") or self.w3.eth.gas_price
    gas_cost_eth = float(self.w3.from_wei(gas * gas_price_wei, "ether"))
    return gas_cost_eth * eth_price

  def wait_tx_is_mined(self, tx_hash: Hash32 | HexBytes | HexStr, timeout: int = DEFAULT_TIMEOUT_ORDERS):
    self.logger.info(f"Waiting for transaction {tx_hash.hex()} to be mined...")
    receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
    self.logger.info(f"Transaction {tx_hash.hex()} mined in block {receipt.blockNumber} with status {receipt.status}")
    return receipt

  def wait_till_coins_arrive(self, token: Token, timeout_seconds: int = DEFAULT_TIMEOUT_ORDERS) -> bool:
    self.logger.info(f"Waiting for {token.symbol} to arrive in wallet {self.wallet.address}...")

    balance_before = token.contract.functions.balanceOf(self.wallet.address).call()
    start_time = time.time()

    while True:
      elapsed_time = time.time() - start_time
      if elapsed_time > timeout_seconds:
        self.logger.warning(f"Timeout: Coins ({token.symbol}) did not arrive within {timeout_seconds // 60} minutes.")
        return False

      balance_after = token.contract.functions.balanceOf(self.wallet.address).call()

      if balance_after > balance_before:
        self.logger.info(
          f"Coins arrived! Balance before: {token.to_human(balance_before)}, "
          f"after: {token.to_human(balance_after)} (Wait time: {int(elapsed_time)}s)"
        )
        return True

      time.sleep(5)
