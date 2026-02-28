from typing import Dict

from eth_utils import Network

from blockchain.Token import Tokens


class DepositAddresses:
  """Class representing deposit addresses for a specific token across multiple networks."""

  def __init__(self, token: Tokens):
    self._token = token
    self._networks: Dict[Network, str] = {}

  def add_network_address(self, network: Network, address: str):
    """Add or update a deposit address for a specific network."""
    self._networks[network] = address

  def get_address(self, network: Network) -> str | None:
    """Get the deposit address for a given network."""
    return self._networks.get(network)
