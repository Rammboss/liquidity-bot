import asyncio
import datetime

from Configurations import COINBASE_EURC_USDC_TICKER, EURO_USDC_UNI_V3_POOL_ADDRESS
from blockchain.Token import Tokens
from common.logger import get_logger
from database.database import Database
from services.Executor import Executor
from services.IndexerService import IndexerService
from services.UniswapArbitrageAnalyzer import UniswapArbitrageAnalyzer
from services.UniswapPositionAnalyzer import UniswapPositionAnalyzer


class Application:
  def __init__(self):
    self.logger = get_logger()
    self.db = Database()
    self.tasks = []

  async def _start_services(
      self,
      starting_date: datetime.datetime,
      starting_balance_eth: float,
      starting_balance_eurc: float,
      starting_balance_usdc: float,
      target_qty: float,
      arbitrage_bot_enabled: bool,
      uniswap_position_manger_enabled: bool,
      indexer_enabled: bool,
  ):
    self.db.init()

    tasks = []

    # 1. Indexer Service
    if indexer_enabled:
      indexer = IndexerService(self.db)
      tasks.append(indexer.run())

    # 2. Uniswap Position Analyzer
    if uniswap_position_manger_enabled:
      uniswap_position_analyzer = UniswapPositionAnalyzer(self.db)
      tasks.append(uniswap_position_analyzer.run())

    # 3. Arbitrage & Executor
    if arbitrage_bot_enabled:
      executor = Executor()
      tasks.append(executor.run())

      coinbase_uniswap_arbitrage_analyzer = UniswapArbitrageAnalyzer(
        starting_date,
        starting_balance_eth,
        starting_balance_eurc,
        starting_balance_usdc,
        target_qty,
        COINBASE_EURC_USDC_TICKER,
        EURO_USDC_UNI_V3_POOL_ADDRESS,
        Tokens.EURC,
        Tokens.USDC,
        executor
      )
      tasks.append(coinbase_uniswap_arbitrage_analyzer.run())

    if tasks:
      await asyncio.gather(*tasks)
    else:
      print("No services enabled. Standing by.")

  def run(
      self,
      starting_date: datetime.datetime,
      starting_balance_eth: float,
      starting_balance_eurc: float,
      starting_balance_usdc: float,
      target_qty: float,
      arbitrage_bot_enabled: bool,
      uniswap_position_manger_enabled: bool,
      indexer_enabled: bool,
  ):
    asyncio.run(self._start_services(
      starting_date=starting_date,
      starting_balance_eth=starting_balance_eth,
      starting_balance_eurc=starting_balance_eurc,
      starting_balance_usdc=starting_balance_usdc,
      target_qty=target_qty,
      arbitrage_bot_enabled=arbitrage_bot_enabled,
      uniswap_position_manger_enabled=uniswap_position_manger_enabled,
      indexer_enabled=indexer_enabled
    ))


if __name__ == "__main__":
  app = Application()
  app.run(
    starting_date=datetime.datetime(2026, 2, 25, 22, 37, 34),
    starting_balance_eth=0.36,
    starting_balance_eurc=2803.649488,
    starting_balance_usdc=2997.099793,
    target_qty=4000,
    arbitrage_bot_enabled=True,
    uniswap_position_manger_enabled=False,
    indexer_enabled=False
  )
