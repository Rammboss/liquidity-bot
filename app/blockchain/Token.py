import os
from decimal import Decimal
from enum import StrEnum

from dotenv import load_dotenv
from web3 import Web3

from blockchain.AbiService import AbiService

load_dotenv()


class Tokens(StrEnum):
  USDC = "USDC"
  ETH = "ETH"
  EURC = "EURC"

  def to_string(self) -> str:
    """Return the string value of the token."""
    return str(self)

  @staticmethod
  def from_address(address: str, chain_id: int = 1) -> Tokens:
    """Return the token enum based on the contract address and chain ID."""
    mapping = Tokens.get_mapping()
    if chain_id not in mapping:
      raise ValueError(f"Unsupported chain ID: {chain_id}")

    for token_name, token_address in mapping[chain_id].items():
      if token_address.lower() == address.lower():
        return Tokens[token_name]

    raise ValueError(f"Address {address} not found in mapping for chain ID {chain_id}")

  def to_address(self, chain_id: int = 1) -> str:
    """Return the token contract address for a given chain ID."""
    mapping = Tokens.get_mapping()
    if chain_id not in mapping:
      raise ValueError(f"Unsupported chain ID: {chain_id}")

    address = mapping[chain_id].get(self.to_string())
    if not address:
      raise ValueError(f"Token not mapped for chain ID {chain_id}: {self.to_string()}")

    return address

  @staticmethod
  def get_mapping():
    return {
      1: {  # Ethereum Mainnet
        "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # verified :contentReference[oaicite:0]{index=0}
        "ETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",  # WETH
        "EURC": "0x1aBaEA1f7C830bD89Acc67eC4af516284b1bC33c",
      },
      11155111: {
        "USDC": "0x94a9D9AC8a22534E3FaCa9F4e7F2E2cf85d5E4C8",
        "ETH": "0xfFf9976782d46CC05630D1f6eBAb18b2324d6B14",  # WETH
      },
      130: {  # Unichain
        "USDC": "0x078D782b760474a361dDA0AF3839290b0EF57AD6",
        "ETH": "0x4200000000000000000000000000000000000006",
      },
      42161: {  # Arbitrum Mainnet
        "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # verified :contentReference[oaicite:1]{index=1}
        "ETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",  # WETH on Arbitrum
      },
      43114: {  # Avalanche C‑Chain
        "USDC": "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E",  # verified
        "ETH": "0x49D5c2BdFfac6CE2BFdB6640F4F80f226bc10bAB",  # WETH on Avalanche
      },
      56: {  # BNB
        "USDC": "0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d",  # verified :contentReference[oaicite:2]{index=2}
        "ETH": "0x2170Ed0880ac9A755fd29B2688956BD959F933F8",  # WETH on BNB
      },
      8453: {  # Base
        "USDC": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # verified :contentReference[oaicite:3]{index=3}
        "ETH": "0x4200000000000000000000000000000000000006",
        # WETH on Base (same as Optimism) :contentReference[oaicite:4]{index=4}
      },
      10: {  # Optimism
        "USDC": "0x0b2C639c533813f4Aa9D7837CAf62653d097Ff85",  # verified :contentReference[oaicite:5]{index=5}
        "ETH": "0x4200000000000000000000000000000000000006",  # WETH on Optimism
      },
      137: {  # Polygon PoS
        "USDC": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",  # verified :contentReference[oaicite:6]{index=6}
        "ETH": "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",  # WETH on Polygon
      },
      81457: {  # Blast
        "USDC": "0x4300000000000000000000000000000000000003",  # USDB
        "ETH": "0x4300000000000000000000000000000000000004",
      },
      # 7777777: {  # Zora
      #   "USDC": "None",
      #   "ETH": "0x4200000000000000000000000000000000000006",  # WETH on Zora :contentReference[oaicite:7]{index=7}
      # },
      480: {  # WorldChain
        "USDC": "0x79A02482A880bCE3F13e09Da970dC34db4CD24d1",
        "ETH": "0x4200000000000000000000000000000000000006",
      },
    }


class Token:
  def __init__(self, token: Tokens):
    self._cache = {}
    self.w3 = Web3(Web3.HTTPProvider(os.getenv("RPC_URL")))
    self.address = self.w3.to_checksum_address(token.to_address(self.w3.eth.chain_id))
    self.abi_service = AbiService()
    self.token = token

    if self.address not in self._cache:
      self.contract = self.w3.eth.contract(
        address=self.address,
        abi=self.abi_service.get_abi("ERC20")
      )

      decimals = self.contract.functions.decimals().call()
      symbol = self.contract.functions.symbol().call()
      name = self.contract.functions.name().call()

      self._cache[self.address] = {
        "name": name,
        "decimals": decimals,
        "symbol": symbol,
      }

    self.decimals = self._cache[self.address]["decimals"]
    self.symbol = self._cache[self.address]["symbol"]
    self.name = self._cache[self.address]["name"]

  def to_human(self, raw_amount: int) -> float:
    return float(Decimal(raw_amount) / Decimal(10 ** self.decimals))

  def to_raw(self, human_amount: float) -> int:
    return int(Decimal(human_amount) * Decimal(10 ** self.decimals))

  def format(self, raw_amount: int, precision: int = 6) -> str:
    human = self.to_human(raw_amount)
    return f"{human:.{precision}f} {self.symbol}"
