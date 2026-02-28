from hexbytes import HexBytes

from blockchain.Token import Tokens
from blockchain.WalletService import WalletService
from blockchain.uniswap.Pool import Pool
from common.AccountManager import AccountManager
from exchanges.Coinbase.Coinbase import Coinbase
from execution.BasicTask import BasicTask
from common.logger import get_logger


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

  async def run(self):
    if self.sell_coinbase_buy_uni:
      # 2. Kauf auf Uniswap
      self.logger.info(f"Executing buy on Uniswap for {self.t1_expected_outcome}")
      tx_hash = await self.pool.swap(
        token_in=Tokens.USDC,
        amount_in=self.t1_expected_outcome,
        eth_price=self.eth_price,
        min_amount_out=self.t2_expected_outcome * 0.999 # Slippage von 0.1% einplanen
      )
      self.logger.info(f"Executing sell on Coinbase for {self.t1_start_amount} with expected outcome {self.t2_expected_outcome}")
      order = self.coinbase.create_order(
        side="sell",
        type_="limit",
        amount=self.t1_start_amount,
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
        min_amount_out=self.t2_expected_outcome * 0.999 # Slippage von 0.1% einplanen
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

    await self.coinbase.wait_order_filled(order.get("order_id"))
    self.logger.info(f"Coinbase order filled: {order.get('order_id')}")

    self.wallet_service.wait_tx_is_mined(HexBytes(tx_hash), timeout=120)
