import json
from enum import StrEnum
from pathlib import Path

from web3 import Web3
from web3.contract import Contract as Web3Contract

from blockchain.Token import Tokens
from logger import get_logger

BASE_PATH = Path(__file__).resolve().parent / "abis"
logger = get_logger()


class Contract(StrEnum):
  UNISWAP_V2_ROUTER = "UNISWAP_V2_ROUTER"
  UNISWAP_V2_FACTORY = "UNISWAP_V2_FACTORY"
  POOL_USDC_WETH = "POOL_USDC_WETH"
  WETH = "WETH"
  USDC = "USDC"
  EURC = "EURC"
  UNISWAP_V3_QUOTER = "UNISWAP_V3_QUOTER"
  UNISWAP_V4_QUOTER = "UNISWAP_V4_QUOTER"
  UNIVERSAL_ROUTER = "UNIVERSAL_ROUTER"
  NFTM = "NFTM"
  PERMIT2 = "PERMIT2"

  def to_string(self) -> str:
    """Return the string value of the token."""
    return str(self)

  def to_address(self, chain_id: int = 1) -> str:
    """Return the token contract address for a given chain ID."""
    mapping = {
      1: {  # Mainnet
        "UNISWAP_V2_FACTORY": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
        "UNISWAP_V2_ROUTER": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
        "POOL_USDC_WETH": "0xB4e16d0168e52d35CaCD2c6185b44281Ec28C9Dc",
        "UNISWAP_V3_QUOTER": "0x61fFE014bA17989E743c5F6cB21bF9697530B21e",
        "UNISWAP_V4_QUOTER": "0x52f0e24d1c21c8a0cb1e5a5dd6198556bd9e1203",
        "UNIVERSAL_ROUTER": "0x66a9893cC07D91D95644AEDD05D03f95e1dBA8Af",
        "PERMIT2": "0x000000000022D473030F116dDEE9F6B43aC78BA3",
        "WETH": Tokens.ETH.to_address(1),
        "USDC": Tokens.USDC.to_address(1),
        "EURC": Tokens.EURC.to_address(1),
        "NFTM": "0xC36442b4a4522E871399CD717aBDD847Ab11FE88",
      },
      11155111: {  # Sepolia - TESTNET
        "UNISWAP_V2_FACTORY": "0xF62c03E08ada871A0bEb309762E260a7a6a880E6",
        "UNISWAP_V2_ROUTER": "0xeE567Fe1712Faf6149d80dA1E6934E354124CfE3",
        "POOL_USDC_WETH": "0x06d1080CDCBF8Ad77A65A40f4484E93eA6180269",
        "UNISWAP_V3_QUOTER": "",
        "UNISWAP_V4_QUOTER": "",
        "UNIVERSAL_ROUTER": "0x492e6456d9528771018deb9e87ef7750ef184104",
        "PERMIT2": "0x000000000022D473030F116dDEE9F6B43aC78BA3",
        "WETH": Tokens.ETH.to_address(11155111),
        "USDC": Tokens.USDC.to_address(11155111),
      },
      130: {  # Unichain
        "UNISWAP_V2_FACTORY": "0x1f98400000000000000000000000000000000002",
        "UNISWAP_V2_ROUTER": "0x284f11109359a7e1306c3e447ef14d38400063ff",
        "POOL_USDC_WETH": "0x8cBf356eCF5aE7035583543479996250178527F4",
        "UNISWAP_V3_QUOTER": "0x385a5cf5f83e99f7bb2852b6a19c3538b9fa7658",
        "UNISWAP_V4_QUOTER": "0x333e3c607b141b18ff6de9f258db6e77fe7491e0",
        "UNIVERSAL_ROUTER": "0xef740bf23acae26f6492b10de645d6b98dc8eaf3",
        "PERMIT2": "0x000000000022D473030F116dDEE9F6B43aC78BA3",
        "WETH": Tokens.ETH.to_address(130),
        "USDC": Tokens.USDC.to_address(130),
      },
      42161: {  # Arbitrum
        "UNISWAP_V2_FACTORY": "0xf1D7CC64Fb4452F05c498126312eBE29f30Fbcf9",
        "UNISWAP_V2_ROUTER": "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
        "POOL_USDC_WETH": "0xF64Dfe17C8b87F012FCf50FbDA1D62bfA148366a",
        "UNISWAP_V3_QUOTER": "0x61fFE014bA17989E743c5F6cB21bF9697530B21e",
        "UNISWAP_V4_QUOTER": "0x3972c00f7ed4885e145823eb7c655375d275a1c5",
        "UNIVERSAL_ROUTER": "0xA51afAFe0263b40EdaEf0Df8781eA9aa03E381a3",
        "PERMIT2": "0x000000000022D473030F116dDEE9F6B43aC78BA3",
        "WETH": Tokens.ETH.to_address(42161),
        "USDC": Tokens.USDC.to_address(42161),
      },
      43114: {  # Avalanche
        "UNISWAP_V2_FACTORY": "0x9e5A52f57b3038F1B8EeE45F28b3C1967e22799C",
        "UNISWAP_V2_ROUTER": "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
        "POOL_USDC_WETH": "0x7a8fe1F02073401F06F177a272073Faf0E216895",
        "UNISWAP_V3_QUOTER": "0xbe0F5544EC67e9B3b2D979aaA43f18Fd87E6257F",
        "UNISWAP_V4_QUOTER": "0xbe40675bb704506a3c2ccfb762dcfd1e979845c2",
        "UNIVERSAL_ROUTER": "0x94b75331ae8d42c1b61065089b7d48fe14aa73b7",
        "PERMIT2": "0x000000000022D473030F116dDEE9F6B43aC78BA3",
        "WETH": Tokens.ETH.to_address(43114),
        "USDC": Tokens.USDC.to_address(43114),
      },
      56: {  # BNB
        "UNISWAP_V2_FACTORY": "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6",
        "UNISWAP_V2_ROUTER": "0x4752ba5DBc23f44D87826276BF6Fd6b1C372aD24",
        "POOL_USDC_WETH": "0x7Ae9361Ee7Eb76b69Ac0B78568d5eCa683F740f0",
        "UNISWAP_V3_QUOTER": "0x78D78E420Da98ad378D7799bE8f4AF69033EB077",
        "UNISWAP_V4_QUOTER": "0x9f75dd27d6664c475b90e105573e550ff69437b0",
        "UNIVERSAL_ROUTER": "0x1906c1d672b88cd1b9ac7593301ca990f94eae07",
        "PERMIT2": "0x000000000022D473030F116dDEE9F6B43aC78BA3",
        "WETH": Tokens.ETH.to_address(56),
        "USDC": Tokens.USDC.to_address(56),
      },
      8453: {  # Base
        "UNISWAP_V2_FACTORY": "0x8909Dc15e40173Ff4699343b6eB8132c65e18eC6",
        "UNISWAP_V2_ROUTER": "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24",
        "POOL_USDC_WETH": "0x88A43bbDF9D098eEC7bCEda4e2494615dfD9bB9C",
        "UNISWAP_V3_QUOTER": "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a",
        "UNISWAP_V4_QUOTER": "0x0d5e0f971ed27fbff6c2837bf31316121532048d",
        "UNIVERSAL_ROUTER": "0x6ff5693b99212da76ad316178a184ab56d299b43",
        "PERMIT2": "0x000000000022D473030F116dDEE9F6B43aC78BA3",
        "WETH": Tokens.ETH.to_address(8453),
        "USDC": Tokens.USDC.to_address(8453),
      },
      10: {  # Optimism
        "UNISWAP_V2_FACTORY": "0x0c3c1c532F1e39EdF36BE9Fe0bE1410313E074Bf",
        "UNISWAP_V2_ROUTER": "0x4A7b5Da61326A6379179b40d00F57E5bbDC962c2",
        "POOL_USDC_WETH": "0x4C43646304492A925E335f2b6d840C1489f17815",
        "UNISWAP_V3_QUOTER": "0x61fFE014bA17989E743c5F6cB21bF9697530B21e",
        "UNISWAP_V4_QUOTER": "0x1f3131a13296fb91c90870043742c3cdbff1a8d7",
        "UNIVERSAL_ROUTER": "0x851116d9223fabed8e56c0e6b8ad0c31d98b3507",
        "PERMIT2": "0x000000000022D473030F116dDEE9F6B43aC78BA3",
        "WETH": Tokens.ETH.to_address(10),
        "USDC": Tokens.USDC.to_address(10),
      },
      137: {  # Polygon
        "UNISWAP_V2_FACTORY": "0x9e5A52f57b3038F1B8EeE45F28b3C1967e22799C",
        "UNISWAP_V2_ROUTER": "0xedf6066a2b290C185783862C7F4776A2C8077AD1",
        "POOL_USDC_WETH": "0x67473ebdBFD1e6Fc4367462d55eD1eE56e1963FA",
        "UNISWAP_V3_QUOTER": "0x61fFE014bA17989E743c5F6cB21bF9697530B21e",
        "UNISWAP_V4_QUOTER": "0xb3d5c3dfc3a7aebff71895a7191796bffc2c81b9",
        "UNIVERSAL_ROUTER": "0x1095692a6237d83c6a72f3f5efedb9a670c49223",
        "PERMIT2": "0x000000000022D473030F116dDEE9F6B43aC78BA3",
        "WETH": Tokens.ETH.to_address(137),
        "USDC": Tokens.USDC.to_address(137),
      },
      81457: {  # Blast
        "UNISWAP_V2_FACTORY": "0x5C346464d33F90bABaf70dB6388507CC889C1070",
        "UNISWAP_V2_ROUTER": "0xBB66Eb1c5e875933D44DAe661dbD80e5D9B03035",
        "POOL_USDC_WETH": "0xAd06cD451fe4034a6dD515Af08E222a3d95B4A1C",
        "UNISWAP_V4_QUOTER": "0x6f71cdcb0d119ff72c6eb501abceb576fbf62bcf",
        "UNIVERSAL_ROUTER": "0xeabbcb3e8e415306207ef514f660a3f820025be3",
        "PERMIT2": "0x000000000022D473030F116dDEE9F6B43aC78BA3",
        "WETH": Tokens.ETH.to_address(81457),
        "USDC": Tokens.USDC.to_address(81457),
      },
      # 7777777: {  # Zora
      #   "UNISWAP_V2_FACTORY": "0x0F797dC7efaEA995bB916f268D919d0a1950eE3C",
      #   "UNISWAP_V2_ROUTER": "0xa00F34A632630EFd15223B1968358bA4845bEEC7",
      #   "WETH": Tokens.ETH.to_address(7777777),
      #   "USDC": Tokens.USDC.to_address(7777777),
      # },
      480: {  # WorldChain
        "UNISWAP_V2_FACTORY": "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
        "UNISWAP_V2_ROUTER": "0x541aB7c31A119441eF3575F6973277DE0eF460bd",
        "POOL_USDC_WETH": "0x5A5189307EAe50B0ef16EFF3812B798091A4dd52",
        "UNISWAP_V3_QUOTER": "0x10158D43e6cc414deE1Bd1eB0EfC6a5cBCfF244c",
        "UNISWAP_V4_QUOTER": "0x55d235b3ff2daf7c3ede0defc9521f1d6fe6c5c0",
        "UNIVERSAL_ROUTER": "0x8ac7bee993bb44dab564ea4bc9ea67bf9eb5e743",
        "PERMIT2": "0x000000000022D473030F116dDEE9F6B43aC78BA3",
        "WETH": Tokens.ETH.to_address(480),
        "USDC": Tokens.USDC.to_address(480),
      },
    }

    if chain_id not in mapping:
      raise ValueError(f"Unsupported chain ID: {chain_id}")

    address = mapping[chain_id].get(self.to_string())
    if not address:
      raise ValueError(f"Token not mapped for chain ID {chain_id}: {self.to_string()}")

    return address

  def load_abi(self, chain_id: int):
    """
    Generalized ABI loader based on contract name and chain_id.
    Expects JSON files under abis/<chain_folder>/<contract_name>.json.
    Throws FileNotFoundError if ABI file is missing.
    """
    # Map common folder names for chains
    chain_folder_map = {}

    # Use "default" folder if chain_id not mapped
    folder = chain_folder_map.get(chain_id, "default")

    if chain_id not in chain_folder_map:
      logger.debug(f"No specific folder for chain_id={chain_id}, using 'default'")

    # Construct path: BASE_PATH/<chain_folder>/<contract_name>.json
    abi_file = BASE_PATH / folder / f"{self.to_string().lower()}.json"

    if not abi_file.exists():
      raise FileNotFoundError(f"ABI file not found for {self.to_string()} on chain {chain_id}: {abi_file}")

    with abi_file.open("r", encoding="utf-8") as f:
      return json.load(f)

  def get_contract(self, w3: Web3, chain_id: int) -> Web3Contract:
    """
    Return a Web3 contract instance for this contract and chain.
    """
    abi = self.load_abi(chain_id)
    address = self.to_address(chain_id)
    return w3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)
