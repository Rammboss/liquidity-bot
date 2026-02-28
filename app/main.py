import asyncio

from Configurations import COINBASE_EURC_USDC_TICKER, EURO_USDC_UNI_V3_POOL_ADDRESS
from blockchain.Token import Tokens
from database.database import Database
from logger import get_logger
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
    # coinbase_uniswap_arbitrage_analyzer = UniswapArbitrageAnalyzer(ETH_EURC_USDC_TICKER,
    #                                                                ETH_USDC_UNI_V3_POOL_ADDRESS,
    #                                                                Tokens.ETH,
    #                                                                Tokens.USDC
    #                                                                )

    # Use a ThreadPool to run blocking code without stopping the event loop
    await asyncio.gather(
      # tg.create_task(indexer.run())
      # tg.create_task(uniswap_position_analyzer.run())
      coinbase_uniswap_arbitrage_analyzer.run(),
      executor.run()
    )
    # with ThreadPoolExecutor() as pool:
    #   await asyncio.gather(
    #     # loop.run_in_executor(pool, indexer.run, ),
    #     # loop.run_in_executor(pool, uniswap_position_analyzer.run, ),
    #     loop.run_in_executor(pool, coinbase_uniswap_arbitrage_analyzer.run, )
    #   )

  def run(self):
    asyncio.run(self._start_services())


if __name__ == "__main__":
  app = Application()
  app.run()