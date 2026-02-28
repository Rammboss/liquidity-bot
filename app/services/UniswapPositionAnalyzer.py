import math
import os
from math import sqrt
from time import sleep

import dotenv
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

from blockchain.Contract import Contract
from database.repositories import IndexedBlockRepository, PositionRepository
from common.logger import get_logger
from blockchain.AbiService import AbiService
from blockchain.uniswap.NoneFungibleTokenManager import NoneFungibleTokenManager
from blockchain.uniswap.Pool import Pool
from blockchain.uniswap.QuoterV3 import QuoterV3

dotenv.load_dotenv()


class UniswapPositionAnalyzer:
  def __init__(self, db):
    self.logger = get_logger()
    self.abi_service = AbiService()
    self.db = db
    self.w3 = Web3(Web3.HTTPProvider(os.getenv("RPC_URL")))
    self.pool = Pool("0x95DBB3C7546F22BCE375900AbFdd64a4E5bD73d6")
    self.account: LocalAccount = Account.from_key(os.getenv("PRIVATE_KEY"))
    self.nftm = NoneFungibleTokenManager(Contract.NFTM.to_address(self.w3.eth.chain_id))
    self.quoter_v3 = QuoterV3(Contract.UNISWAP_V3_QUOTER.to_address(self.w3.eth.chain_id))

    self.block_status = None
    self.position_repo = None
    self._running = False

  def run(self):
    self._running = True

    while self._running:
      with self.db.session() as session:
        self.block_status = IndexedBlockRepository(session)
        self.position_repo = PositionRepository(session)

        if not self.block_status.get_latest().synced:
          self.logger.info("Waiting for indexer to sync...")
          sleep(10)
          continue

        self.logger.info("Analyzing positions...")
        positions = self.position_repo.get_active_positions()

        for position in positions:
          self.analyze_position(position)

        sleep(10)

  def get_latest_amounts(self, position):

    # slot0 contains the current sqrtPriceX96
    slot0 = self.pool.pool_contract.functions.slot0().call()
    sqrt_price_x96 = slot0[0]

    # 2. Convert Ticks to sqrtPrice
    # tick_to_sqrt_price formula: sqrt(1.0001^tick) * 2^96
    sqrt_p = sqrt_price_x96 / (2 ** 96)
    sqrt_p_lower = sqrt(1.0001 ** position.tick_lower)
    sqrt_p_upper = sqrt(1.0001 ** position.tick_upper)

    # 3. Calculate Amounts based on range
    liquidity = position.liquidity

    amount0 = 0
    amount1 = 0

    if sqrt_p < sqrt_p_lower:
      # Out of range (Price too low) -> 100% Token0
      amount0 = liquidity * (sqrt_p_upper - sqrt_p_lower) / (sqrt_p_lower * sqrt_p_upper)
    elif sqrt_p > sqrt_p_upper:
      # Out of range (Price too high) -> 100% Token1
      amount1 = liquidity * (sqrt_p_upper - sqrt_p_lower)
    else:
      # In range -> Mixed
      amount0 = liquidity * (sqrt_p_upper - sqrt_p) / (sqrt_p * sqrt_p_upper)
      amount1 = liquidity * (sqrt_p - sqrt_p_lower)

    return amount0, amount1

  def get_claimable_fees(self, position):
    # Max uint128 to ensure we "ask" for everything available
    max_uint128 = 2 ** 128 - 1

    # The 'recipient' address doesn't matter for a .call()
    # as it doesn't execute on-chain.
    recipient = self.account.address

    try:
      fees = self.nftm.contract.functions.collect((
        position.token_id,
        recipient,
        max_uint128,
        max_uint128
      )).call({'from': self.account.address})

      return fees[0], fees[1]

    except Exception as e:
      self.logger.error(f"Error fetching fees for {position.token_id}: {e}")
      return {"token0_fees": 0, "token1_fees": 0}

  def analyze_position(self, position):
    # 1. Calculate current assets
    amount0, amount1 = self.get_latest_amounts(position)

    position.current_amount0 = amount0
    position.current_amount1 = amount1

    # 2. Calculate Ratio
    amount0_initial = position.deposited_amount0
    amount1_initial = position.deposited_amount1
    diff0 = amount0 - amount0_initial
    diff1 = amount1 - amount1_initial

    # 3. Get current price (token1 per token0)
    price = self.quoter_v3.quote_exact_input_single(
      token_in=self.pool.token0.address,
      token_out=self.pool.token1.address,
      fee=500,
      amount_in=10 ** self.pool.token0.decimals
    )

    # --- LP current value ---
    lp_value = amount0 * price.amountOut + amount1

    # --- HODL value (if you held initial amounts) ---
    hodl_value = amount0_initial * price.amountOut + amount1_initial

    il = (lp_value / hodl_value) - 1 if hodl_value > 0 else 0

    self.logger.info(f"LP Value: {lp_value:.6f}")
    self.logger.info(f"HODL Value: {hodl_value:.6f}")
    self.logger.info(f"Impermanent Loss: {il:.4f} Token(negative)")

    self.logger.info(
      f"-------------------{position.token_id}: {self.pool.token0.format(amount0)} / "
      f"{self.pool.token1.format(amount1)}---------------------")

    self.logger.info(
      f"Pos {position.id}: Initial balances: {self.pool.token0.format(amount0_initial)} / "
      f"{self.pool.token1.format(amount1_initial)}")
    self.logger.info(f"Diff {self.pool.token0.symbol}: {self.pool.token0.format(diff0)}")
    self.logger.info(f"Diff {self.pool.token1.symbol}: {self.pool.token1.format(diff1)}")

    fees0, fees1 = self.get_claimable_fees(position)
    self.logger.info(
      f"Pos {position.id}: Claimable fees {self.pool.token0.format(fees0)} / {self.pool.token1.format(fees1)}")

    self.position_repo.save(position)

  def calculate_v3_il(self, p_current, p_initial, p_low, p_high):
    """
    Calculates IL for a Uniswap v3 position.

    :param p_current: Current price of the asset
    :param p_initial: Price when you deposited
    :param p_low: The lower bound of your range
    :param p_high: The upper bound of your range
    """

    def get_value_at_price(p, p_l, p_h):
      # Ensure price is clamped within the range for value calculations
      p = max(min(p, p_h), p_l)
      # Value of a v3 position formula (simplified relative units)
      return (2 * math.sqrt(p) - math.sqrt(p_l) - p / math.sqrt(p_h))

    # 1. Value of the LP position at current price
    v_lp = get_value_at_price(p_current, p_low, p_high)

    # 2. Value if we held the original assets (HODL)
    # This requires knowing the specific amounts of X and Y at deposit
    # For a relative IL %, we calculate the value of the initial LP at p_current
    sqrt_p = math.sqrt(p_initial)
    sqrt_pl = math.sqrt(p_low)
    sqrt_ph = math.sqrt(p_high)

    # Initial liquidity amounts (relative)
    x_init = (sqrt_ph - sqrt_p) / (sqrt_p * sqrt_ph)
    y_init = sqrt_p - sqrt_pl

    v_hold = (x_init * p_current) + y_init

    # 3. Impermanent Loss
    il = (v_lp / v_hold) - 1
    return il

  def calculate_impermanent_loss(self, initial_price, current_price):
    """
    Calculates the Impermanent Loss (IL) for a 50/50 liquidity pool.

    :param initial_price: Price of the asset when deposited.
    :param current_price: Price of the asset at the current time.
    :return: IL as a percentage (e.g., -0.057 for -5.7%).
    """
    # Calculate the price ratio (P)
    price_ratio = current_price / initial_price

    # Standard IL formula: (2 * sqrt(P) / (1 + P)) - 1
    il_decimal = (2 * math.sqrt(price_ratio) / (1 + price_ratio)) - 1

    return il_decimal
