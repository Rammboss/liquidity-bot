import os

import dotenv
from telegram.constants import ParseMode
from web3 import Web3

from blockchain.Token import Token
from blockchain.WalletService import WalletService
from common.TelegramServices import TelegramServices
from common.logger import get_logger
from exchanges.Coinbase.Coinbase import Coinbase
from execution.BasicTask import BasicTask

dotenv.load_dotenv()


class WalletWithdrawalTask(BasicTask):
  def __init__(
      self,
      wallet_service: WalletService,
      send_token: Token,
      destination: str,
      eth_price: float,
      telegram: TelegramServices,
      coinbase: Coinbase,
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
    self.telegram = telegram
    self.coinbase = coinbase

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

    latest_block = self.w3.eth.get_block('latest')
    # 2. Your manual Priority Fee (0.01 Gwei)
    base_fee = latest_block['baseFeePerGas']
    prio_fee = self.w3.to_wei(0.005, 'gwei')

    max_fee_per_gas = int(base_fee * 1.125) + prio_fee

    tx = self.send_token.contract.functions.transfer(
      self.destination,
      raw_withdraw_amount
    ).build_transaction({
      "from": self.wallet_service.wallet.address,
      "nonce": self.w3.eth.get_transaction_count(self.wallet_service.wallet.address),
      "maxFeePerGas": max_fee_per_gas,
      'maxPriorityFeePerGas': prio_fee
    })

    gas = self.w3.eth.estimate_gas(tx)

    current_base_fee = self.w3.eth.get_block('latest')['baseFeePerGas']

    # This is what you will likely actually pay
    estimated_actual_cost = float(self.w3.from_wei(tx['gas'] * (current_base_fee + prio_fee), "ether"))

    gas_cost_usd = estimated_actual_cost * self.eth_price
    self.logger.info(f"Estimated gas cost: {estimated_actual_cost:.18f} ETH = {gas_cost_usd:.4f} USD")

    if gas_cost_usd > 1:
      raise ValueError(f"Estimated gas cost of ${gas_cost_usd:.2f} exceeds safety threshold. Aborting withdrawal.")

    signed_tx = self.wallet_service.wallet.sign_transaction(tx)
    tx_hash = self.w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    self.logger.info(f"Withdrawal transaction sent: {tx_hash.hex()}")

    is_mined = self.wallet_service.wait_tx_is_mined(tx_hash, timeout=300)
    self.logger.info("Tx mined.")
    self.logger.info(f"Waiting till funds are available in coinbase...")
    arrived_on_cb = await self.coinbase.wait_till_deposit_arrives(self.send_token)

    if arrived_on_cb and is_mined:
      await self.telegram.native_send(
        f"✅ Wallet→CB transfer done | {self.send_token.to_human(raw_withdraw_amount):.2f} {self.send_token.symbol} | Tx: {tx_hash.hex()[:10]}...",
        ParseMode.HTML
      )

      self.logger.info(f"Withdrawal transaction completed: {tx_hash.hex()}")
    else:
      self.logger.error(f"Withdrawal transaction failed: Status mined: {is_mined}, Status coinbase: {arrived_on_cb}")
