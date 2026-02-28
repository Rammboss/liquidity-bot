import os

import dotenv
from eth_account import Account
from eth_account.signers.local import LocalAccount
from eth_typing import Hash32, HexStr
from hexbytes import HexBytes
from web3 import Web3

from blockchain.Token import Token
from logger import get_logger

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

  def wait_tx_is_mined(self, tx_hash: Hash32 | HexBytes | HexStr, timeout: int = 120):
    self.logger.info(f"Waiting for transaction {tx_hash} to be mined...")
    receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
    self.logger.info(f"Transaction {tx_hash} mined in block {receipt.blockNumber} with status {receipt.status}")
    return receipt
