import os

import dotenv
from web3 import Web3

from blockchain.Token import Token
from blockchain.WalletService import WalletService
from execution.BasicTask import BasicTask
from logger import get_logger

dotenv.load_dotenv()


class WalletWithdrawalTask(BasicTask):
  def __init__(
      self,
      wallet_service: WalletService,
      send_token: Token,
      destination: str,
      eth_price: float,
      amount: float = None,
      priority: int = 5
  ):
    super().__init__(priority)
    self.logger = get_logger()
    self.wallet_service = wallet_service
    self.w3 = Web3(Web3.HTTPProvider(os.getenv("RPC_URL")))
    self.send_token = send_token
    self.destination = destination
    self.amount = amount
    self.eth_price = eth_price

  async def run(self):
    raw_wallet_balance = self.send_token.contract.functions.balanceOf(self.wallet_service.wallet.address).call()

    if self.amount is not None:
      raw_withdraw_amount = self.send_token.to_raw(self.amount)
      if raw_wallet_balance < raw_withdraw_amount:
        raise ValueError(
          f"Insufficient funds. Have {self.send_token.to_human(raw_wallet_balance)}, "
          f"requested {self.amount} {self.send_token.symbol}"
        )
    else:
      raw_withdraw_amount = raw_wallet_balance

    if raw_withdraw_amount <= 0:
      raise ValueError(f"Withdraw amount must be greater than 0 (Balance: {raw_wallet_balance})")

    self.logger.info(f"Withdrawing {self.send_token.to_human(raw_withdraw_amount)} {self.send_token.name} to {self.destination}")

    tx = self.send_token.contract.functions.transfer(
      self.destination,
      raw_withdraw_amount
    ).build_transaction({
      "from": self.wallet_service.wallet.address,
      "nonce": self.w3.eth.get_transaction_count(self.wallet_service.wallet.address),
    })
    gas = self.w3.eth.estimate_gas(tx)
    gas_price_wei = tx.get("maxFeePerGas") or self.w3.eth.gas_price
    gas_cost_eth = float(self.w3.from_wei(gas * gas_price_wei, "ether"))
    gas_cost_usd = gas_cost_eth * self.eth_price
    self.logger.info(f"Estimated gas cost: {gas_cost_eth:.18f} ETH = {gas_cost_usd:.4f} USD")

    if gas_cost_usd > 1:
      raise ValueError(f"Estimated gas cost of ${gas_cost_usd:.2f} exceeds safety threshold. Aborting withdrawal.")

    signed_tx = self.wallet.sign_transaction(tx)
    tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    self.logger.info(f"Withdrawal transaction sent: {tx_hash.hex()}")
