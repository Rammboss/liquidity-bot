import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session


load_dotenv()


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self):
        self._engine = self._create_engine()
        self._session_factory = sessionmaker(
            bind=self._engine,
            autoflush=False,
            autocommit=False,
        )

    def _create_engine(self):
        url = (
            f"postgresql+psycopg2://"
            f"{os.getenv('POSTGRES_USER')}:"
            f"{os.getenv('POSTGRES_PASSWORD')}@"
            f"{os.getenv('POSTGRES_HOST')}:"
            f"{os.getenv('POSTGRES_PORT')}/"
            f"{os.getenv('POSTGRES_DB')}"
        )

        return create_engine(url, pool_pre_ping=True)

    def init(self):
        if os.getenv("RESET_DB") == "true":
            Base.metadata.drop_all(bind=self._engine)

        Base.metadata.create_all(bind=self._engine)

    def session(self) -> Session:
        return self._session_factory()
