from enum import StrEnum


class Network(StrEnum):
  ETH = "ethereum"
  ARBITRUM = "ARBITRUM"
  BASE = "BASE"
  OPTIMISM = "OPTIMISM"
  POLYGON = "POLYGON"
  SUI = "SUI"
  ALGORAND = "ALGORAND"
  NOBLE = "NOBLE"

  @classmethod
  def network_exists(cls, network_str: str) -> bool:
    try:
      cls.from_string(network_str)
      return True
    except ValueError:
      return False

  @classmethod
  def from_string(cls, network_str: str) -> "Network":
    normalized = network_str.strip().upper()

    # Try direct match
    for network in cls:
      if normalized == network.value:
        return network

    # Try alias matching
    for network, alias_set in NETWORK_ALIASES.items():
      if normalized in alias_set:
        return network

    raise ValueError(f"Unknown network: {network_str}")

  def to_string(self) -> str:
    """Return the string value of the network."""
    return str(self.value)


NETWORK_ALIASES: dict[Network, set[str]] = {
  Network.ETH: {"ETH", "ETHEREUM"},
  Network.ARBITRUM: {"ARBITRUM"},
  Network.BASE: {"BASE"},
  Network.ALGORAND: {"ALGO", "ALGORAND", "algorand"},
  Network.NOBLE: {"NOBLE", "noble"},
  Network.OPTIMISM: {"OPTIMISM", "optimism"},
  Network.POLYGON: {"POLYGON", "polygon"},
  Network.SUI: {"SUI", "sui"},
}
