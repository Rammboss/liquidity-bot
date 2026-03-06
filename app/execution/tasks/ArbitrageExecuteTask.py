import asyncio

from hexbytes import HexBytes

from blockchain.Token import Tokens
from blockchain.WalletService import WalletService
from blockchain.uniswap.Pool import Pool
from common.AccountManager import AccountManager
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
      pool_liquidity: float,
      cb_available_volume: float,
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
    self.pool_liquidity = pool_liquidity
    self.cb_available_volume = cb_available_volume
    self.eth_price = eth_price
    self.execution_summary: str | None = None

  async def run(self):
    total_before = self.account_manager.get_total_balances()
    eth_before = total_before.get(Tokens.ETH)

    if self.sell_coinbase_buy_uni:
      self.logger.info(f"Executing buy on Uniswap for {self.t1_expected_outcome}")
      tx_hash = await self.pool.swap(
        token_in=Tokens.USDC,
        amount_in=self.t1_start_amount,
        eth_price=self.eth_price,
        min_amount_out=self.t1_expected_outcome * 0.999
      )
      self.logger.info(
        f"Executing sell on Coinbase for {self.t1_start_amount} with expected outcome {self.t2_expected_outcome}")
      order = self.coinbase.create_order(
        token0=self.pool.token0.token,
        token1=self.pool.token1.token,
        side="sell",
        type_="limit",
        amount=self.t1_expected_outcome,
        price=self.cb_price
      )
      self.logger.info(f"Coinbase sell order created: {order}")
    else:
      self.logger.info(
        f"Executing sell on Uniswap for {self.t1_expected_outcome} with expected outcome {self.t2_expected_outcome}")
      tx_hash = await self.pool.swap(
        token_in=Tokens.EURC,
        amount_in=self.t1_expected_outcome,
        eth_price=self.eth_price,
        min_amount_out=self.t2_expected_outcome * 0.999
      )
      self.logger.info(f"Executing buy on Coinbase for {self.t1_start_amount}")
      order = self.coinbase.create_order(
        token0=self.pool.token0.token,
        token1=self.pool.token1.token,
        side="buy",
        type_="limit",
        amount=self.t1_start_amount,
        price=self.cb_price
      )
      self.logger.info(f"Coinbase buy order created: {order}")

    await self.coinbase.wait_order_filled(order['id'])
    self.logger.info(f"Coinbase order filled: {order['id']}")

    self.wallet_service.wait_tx_is_mined(HexBytes(tx_hash))

    await asyncio.sleep(10)

    total_after = self.account_manager.get_total_balances()
    eth_after = total_after.get(Tokens.ETH)
    profit_usdc = total_after.get(Tokens.USDC) - total_before.get(Tokens.USDC)
    profit_eurc = total_after.get(Tokens.EURC) - total_before.get(Tokens.EURC)

    eth_fees = eth_after - eth_before
    eth_fees_cost_usd = eth_fees * self.eth_price

    total_profit_in_usdc = profit_usdc + profit_eurc * self.cb_price + eth_fees_cost_usd
    self.execution_summary = (
      f"✅ Arb done | PnL: {total_profit_in_usdc:.2f} USDC\n"
      f"USDC: {profit_usdc:.2f} | EURC: {profit_eurc:.2f} | Fee: ${eth_fees_cost_usd:.2f}\n"
      f"Max drainable liquidity(Pool): {self.pool_liquidity:.4f} | Max drainable Volume(CB): {self.cb_available_volume:.4f}"
    )
    self.logger.info(self.execution_summary)

    await asyncio.sleep(10)
    self.logger.info("Arbitrage execution completed")

  def build_control_message(self) -> str | None:
    return self.execution_summary
