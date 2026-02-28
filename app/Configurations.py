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
DEFAULT_TIMEOUT_ORDERS = get_env_float("DEFAULT_TIMEOUT_ORDERS", required=True)
SLIPPAGE = get_env_float("SLIPPAGE", required=True)

EURO_USDC_UNI_V3_POOL_ADDRESS = "0x95DBB3C7546F22BCE375900AbFdd64a4E5bD73d6"
COINBASE_EURC_USDC_TICKER = "EURC/USDC"
