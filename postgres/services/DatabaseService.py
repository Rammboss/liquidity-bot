import logging

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy_utils import create_database, database_exists

import logger

# Base class for ORM models
Base = declarative_base()

sqlalchemy_loggers = [
  "sqlalchemy.engine",  # SQL queries and execution
  "sqlalchemy.pool",  # Connection pool events
  "sqlalchemy.orm",  # ORM operations (flush, commit, etc.)
  "sqlalchemy.dialects",  # Dialect info
]
for name in sqlalchemy_loggers:
  logging.getLogger(name).setLevel(logging.ERROR)


class DatabaseService:
  def __init__(self, user: str, password: str, host: str, port: int, db_name: str):
    # Save all parameters as instance variables
    self.user = user
    self.password = password
    self.host = host
    self.port = port
    self.db_name = db_name
    self.logger = logger.get_logger("DatabaseService")
    ...
    # # Set SQLAlchemy logs to ERROR
    # for name in sqlalchemy_loggers:
    #   sa_logger = logging.getLogger(name)
    #   sa_logger.setLevel(logging.ERROR)
    #   # Attach your logger handlers to SQLAlchemy loggers if desired
    #   for handler in self.logger.handlers:
    #     sa_logger.addHandler(handler)

    self.database_url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db_name}"
    self.engine = create_engine(self.database_url, echo=False)
    self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    self._ensure_database()

  def _ensure_database(self):
    # Temporarily connect to the server without specifying the database
    tmp_url = f"postgresql+psycopg2://{self.user}:{self.password}@{self.host}:{self.port}/postgres"
    tmp_engine = create_engine(tmp_url)
    if not database_exists(self.engine.url):
      create_database(self.engine.url)
      self.logger.debug(f"Database '{self.db_name}' created successfully")
    tmp_engine.dispose()

  def create_tables(self):
    Base.metadata.create_all(bind=self.engine)
    self.logger.debug("Tables created successfully")

  def get_session(self) -> Session:
    return self.SessionLocal()
