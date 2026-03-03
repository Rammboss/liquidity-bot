import asyncio
import datetime
from dataclasses import dataclass
from typing import Awaitable

from Configurations import COINBASE_EURC_USDC_TICKER, EURO_USDC_UNI_V3_POOL_ADDRESS
from blockchain.Token import Tokens
from common.logger import get_logger
from database.database import Database
from services.Executor import Executor
from services.IndexerService import IndexerService
from services.UniswapArbitrageAnalyzer import UniswapArbitrageAnalyzer
from services.UniswapPositionAnalyzer import UniswapPositionAnalyzer


@dataclass(frozen=True)
class RuntimeConfig:
  starting_date: datetime.datetime
  starting_balance_eth: float
  starting_balance_eurc: float
  starting_balance_usdc: float
  target_qty: float
  arbitrage_bot_enabled: bool
  uniswap_position_manager_enabled: bool
  indexer_enabled: bool


class Application:
  def __init__(self) -> None:
    self.logger = get_logger()
    self.db = Database()

  def _build_tasks(self, config: RuntimeConfig) -> list[Awaitable[None]]:
    tasks: list[Awaitable[None]] = []

    if config.indexer_enabled:
      tasks.append(IndexerService(self.db).run())

    if config.uniswap_position_manager_enabled:
      tasks.append(UniswapPositionAnalyzer(self.db).run())

    if config.arbitrage_bot_enabled:
      executor = Executor()
      tasks.append(executor.run())

      arbitrage_analyzer = UniswapArbitrageAnalyzer(
        config.starting_date,
        config.starting_balance_eth,
        config.starting_balance_eurc,
        config.starting_balance_usdc,
        config.target_qty,
        COINBASE_EURC_USDC_TICKER,
        EURO_USDC_UNI_V3_POOL_ADDRESS,
        Tokens.EURC,
        Tokens.USDC,
        executor,
      )
      tasks.append(arbitrage_analyzer.run())

    return tasks

  async def _start_services(self, config: RuntimeConfig) -> None:
    self.db.init()
    tasks = self._build_tasks(config)

    if not tasks:
      self.logger.info("No services enabled. Standing by.")
      return

    await asyncio.gather(*tasks)

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
  ) -> None:
    config = RuntimeConfig(
      starting_date=starting_date,
      starting_balance_eth=starting_balance_eth,
      starting_balance_eurc=starting_balance_eurc,
      starting_balance_usdc=starting_balance_usdc,
      target_qty=target_qty,
      arbitrage_bot_enabled=arbitrage_bot_enabled,
      # Retained the public argument name for backwards compatibility.
      uniswap_position_manager_enabled=uniswap_position_manger_enabled,
      indexer_enabled=indexer_enabled,
    )
    asyncio.run(self._start_services(config))


def _default_runtime_config() -> dict:
  return {
    "starting_date": datetime.datetime(2026, 2, 25, 22, 37, 34),
    "starting_balance_eth": 0.36,
    "starting_balance_eurc": 2803.649488 + 1002.44,
    "starting_balance_usdc": 2997.099793 + 1168.368758,
    "target_qty": 5000,
    "arbitrage_bot_enabled": True,
    "uniswap_position_manger_enabled": False,
    "indexer_enabled": False,
  }


if __name__ == "__main__":
  Application().run(**_default_runtime_config())
