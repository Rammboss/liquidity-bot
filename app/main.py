import asyncio

from database.database import Database
from logger import get_logger
from services.IndexerService import IndexerService


class Application:
    def __init__(self):
        self.logger = get_logger()
        self.db = Database()

    async def _start_services(self):
        self.db.init()

        indexer = IndexerService(self.db)
        indexer_task = asyncio.create_task(indexer.run())

        self.logger.info("All services initialized successfully")
        await indexer_task  # wait forever (indexer runs infinitely)

    def run(self):
        asyncio.run(self._start_services())


if __name__ == "__main__":
    app = Application()
    app.run()
