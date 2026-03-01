import asyncio

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

  async def _start_services(self):
    self.db.init()

    loop = asyncio.get_running_loop()
    indexer = IndexerService(self.db)
    uniswap_position_analyzer = UniswapPositionAnalyzer(self.db)
    executor = Executor()
    coinbase_uniswap_arbitrage_analyzer = UniswapArbitrageAnalyzer(COINBASE_EURC_USDC_TICKER,
                                                                   EURO_USDC_UNI_V3_POOL_ADDRESS,
                                                                   Tokens.EURC,
                                                                   Tokens.USDC,
                                                                   executor)

    await asyncio.gather(
      coinbase_uniswap_arbitrage_analyzer.run(),
      executor.run()
    )

  def run(self):
    asyncio.run(self._start_services())


if __name__ == "__main__":
  app = Application()
  app.run()
