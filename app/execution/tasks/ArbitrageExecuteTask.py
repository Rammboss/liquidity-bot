from hexbytes import HexBytes
from telegram.constants import ParseMode

from blockchain.Token import Tokens
from blockchain.WalletService import WalletService
from blockchain.uniswap.Pool import Pool
from common.AccountManager import AccountManager
from common.TelegramServices import TelegramServices
from common.logger import get_logger
from exchanges.Coinbase.Coinbase import Coinbase
from execution.BasicTask import BasicTask


class ArbitrageExecuteTask(BasicTask):
  def __init__(
      self,
      coinbase: Coinbase,
      pool: Pool,
      wallet_service: WalletService,
      account_manager: AccountManager,
      sell_coinbase_buy_uni: bool,
      t1_stat_amount: float,
      t1_expected_outcome: float,
      t2_expected_outcome: float,
      cb_price: float,
      eth_price: float,
      telegram: TelegramServices,
      priority=1
  ):
    super().__init__(priority)
    self.logger = get_logger()
    self.coinbase = coinbase
    self.pool = pool
    self.wallet_service = wallet_service
    self.account_manager = account_manager

    self.sell_coinbase_buy_uni = sell_coinbase_buy_uni
    self.t1_start_amount = t1_stat_amount
    self.t1_expected_outcome = t1_expected_outcome
    self.t2_expected_outcome = t2_expected_outcome
    self.cb_price = cb_price
    self.eth_price = eth_price
    self.telegram = telegram

  async def run(self):
    total_before = self.account_manager.get_total_balances()

    if self.sell_coinbase_buy_uni:
      # 2. Kauf auf Uniswap
      self.logger.info(f"Executing buy on Uniswap for {self.t1_expected_outcome}")
      tx_hash = await self.pool.swap(
        token_in=Tokens.USDC,
        amount_in=self.t1_start_amount,
        eth_price=self.eth_price,
        min_amount_out=self.t1_expected_outcome * 0.999  # Slippage von 0.1% einplanen
      )
      self.logger.info(f"Executing sell on Coinbase for {self.t1_start_amount} with expected outcome {self.t2_expected_outcome}")
      order = self.coinbase.create_order(
        side="sell",
        type_="limit",
        amount=self.t1_expected_outcome,
        price=self.cb_price
      )
      self.logger.info(f"Coinbase sell order created: {order}")
    else:
      # 2. Verkauf auf Uniswap
      self.logger.info(f"Executing sell on Uniswap for {self.t1_expected_outcome} with expected outcome {self.t2_expected_outcome}")
      tx_hash = await self.pool.swap(
        token_in=Tokens.EURC,
        amount_in=self.t1_expected_outcome,
        eth_price=self.eth_price,
        min_amount_out=self.t2_expected_outcome * 0.999  # Slippage von 0.1% einplanen
      )
      # 1. Kauf auf Coinbase
      self.logger.info(f"Executing buy on Coinbase for {self.t1_start_amount}")
      order = self.coinbase.create_order(
        side="buy",
        type_="limit",
        amount=self.t1_start_amount,
        price=self.cb_price
      )
      self.logger.info(f"Coinbase buy order created: {order}")

    await self.coinbase.wait_order_filled(order['id'])
    self.logger.info(f"Coinbase order filled: {order['id']}")

    self.wallet_service.wait_tx_is_mined(HexBytes(tx_hash))

    total_after = self.account_manager.get_total_balances()
    profit_usdc = total_after.get(Tokens.USDC) - total_before.get(Tokens.USDC)
    profit_eurc = total_after.get(Tokens.EURC) - total_before.get(Tokens.EURC)
    total_profit_in_usdc = profit_usdc + profit_eurc * self.cb_price
    profit_string = f"Total profit: {total_profit_in_usdc:.2f} USDC (USDC: {profit_usdc:.2f}, EURC: {profit_eurc:.2f})"
    self.logger.info(profit_string)
    await self.telegram.native_send(profit_string, parse_mode=ParseMode.HTML)
    self.logger.info("Arbitrage execution completed")
