import os

import dotenv

dotenv.load_dotenv()


def get_env_bool(name: str, required: bool = False) -> bool:
  value = os.getenv(name)
  if value is None:
    if required:
      raise EnvironmentError(f"Missing required environment variable: {name}")
    return False
  return value.lower() in ("1", "true", "yes", "on")


def get_env_float(name: str, required: bool = False) -> float:
  value = os.getenv(name)
  if value is None:
    if required:
      raise EnvironmentError(f"Missing required environment variable: {name}")
    return 0.0
  try:
    return float(value)
  except ValueError:
    raise ValueError(f"Invalid float value for {name}: '{value}'")


def get_env_str(name: str, required: bool = False, default: str = "") -> str:
  """
  Get an environment variable as a string.

  - Strips leading/trailing whitespace.
  - If required and missing, raises EnvironmentError.
  - If not required and missing, returns `default`.
  """
  value = os.getenv(name)
  if value is None:
    if required:
      raise EnvironmentError(f"Missing required environment variable: {name}")
    return default
  return value.strip()


# --- Config ---
# DEV_MODE = get_env_bool("DEV_MODE", required=True)
# DEV_MODE_DISABLE_ORDERS = get_env_bool("DEV_MODE_DISABLE_ORDERS", required=True)
#
# MAX_VOLUME_PER_TRADE = get_env_float("MAX_VOLUME_PER_TRADE", required=True)
# MIN_PROFIT = get_env_float("MIN_PROFIT", required=True)
# PERCENTAGE_OF_AVAILABLE_TOKENS_PER_ARBITRAGE = get_env_float("PERCENTAGE_OF_AVAILABLE_TOKENS_PER_ARBITRAGE",
#                                                              required=True)
DEFAULT_TIMEOUT_ORDERS = get_env_float("DEFAULT_TIMEOUT_ORDERS", required=True)
# DEFAULT_TIMEOUT_PRICES = get_env_float("DEFAULT_TIMEOUT_PRICES", required=True)
# POSTGRES_USER = get_env_str("POSTGRES_USER", required=True)
# POSTGRES_PASSWORD = get_env_str("POSTGRES_PASSWORD", required=True)
# POSTGRES_DB = get_env_str("POSTGRES_DB", required=True)
# POSTGRES_HOST = get_env_str("POSTGRES_HOST", required=False, default="localhost")
# TELEGRAM_BOT_TOKEN = get_env_str("TELEGRAM_BOT_TOKEN", required=True)
# TELEGRAM_CHAT_ID = get_env_str("TELEGRAM_CHAT_ID", required=True)
# AUTO_APPROVE_TOKENS = get_env_bool("AUTO_APPROVE_TOKENS", required=True)
# TICKER_INTERVAL = get_env_float("TICKER_INTERVAL", required=True)
SLIPPAGE = get_env_float("SLIPPAGE", required=True)

EURO_USDC_UNI_V3_POOL_ADDRESS = "0x95DBB3C7546F22BCE375900AbFdd64a4E5bD73d6"
COINBASE_EURC_USDC_TICKER = "EURC/USDC"

ETH_EURC_USDC_TICKER = "ETH/USDC"
ETH_USDC_UNI_V3_POOL_ADDRESS = "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640"
