import math
import os
from decimal import Decimal, ROUND_HALF_UP, getcontext

from dotenv import load_dotenv
from eth_account import Account
from eth_account.datastructures import SignedTransaction
from eth_account.signers.local import LocalAccount
from uniswap_universal_router_decoder import FunctionRecipient, RouterCodec
from web3 import Web3

from blockchain.AbiService import AbiService
from blockchain.Contract import Contract
from blockchain.Token import Token, Tokens
from common.logger import get_logger

load_dotenv()
getcontext().prec = 80


class Pool:
  def __init__(self, address: str):
    self.logger = get_logger()
    self.abi_service = AbiService()
    self.w3 = Web3(Web3.HTTPProvider(os.getenv("RPC_URL")))

    self.chain_id = self.w3.eth.chain_id
    self.pool_contract = self.w3.eth.contract(
      address=self.w3.to_checksum_address(address),
      abi=self.abi_service.get_abi("Pool"))

    self.token0 = Token(Tokens.from_address(self.pool_contract.functions.token0().call()))
    self.token1 = Token(Tokens.from_address(self.pool_contract.functions.token1().call()))
    self.fee = self.pool_contract.functions.fee().call()
    self.tick_spacing = self.pool_contract.functions.tickSpacing().call()

    self.quoter = Contract.UNISWAP_V3_QUOTER.get_contract(self.w3, self.chain_id)
    self.wallet: LocalAccount = Account.from_key(os.getenv("PRIVATE_KEY"))

    self.universal_router = Contract.UNIVERSAL_ROUTER.get_contract(self.w3, self.chain_id)
    self.permit2 = Contract.PERMIT2.get_contract(self.w3, self.chain_id)

  def get_pool_state(self):
    """Fetches the current state of the pool."""
    slot0 = self.pool_contract.functions.slot0().call()
    liquidity = self.pool_contract.functions.liquidity().call()
    return {
      "sqrtPriceX96": slot0[0],
      "tick": slot0[1],
      "liquidity": liquidity
    }

  def get_ask(self, token_in: Token, amount_out: float):
    token_out = self.token1 if token_in.address == self.token0.address else self.token0
    quote_params = {
      "tokenIn": token_in.address,
      "tokenOut": token_out.address,
      "fee": self.fee,
      "amount": token_out.to_raw(amount_out),
      "sqrtPriceLimitX96": 0
    }
    ask_amount = self.quoter.functions.quoteExactOutputSingle(quote_params).call()
    return token_out.to_human(ask_amount[0])

  def get_bid(self, token_in: Token, amount_in: float):
    token_out = self.token1 if token_in.address == self.token0.address else self.token0
    quote_params = {
      "tokenIn": token_in.address,
      "tokenOut": token_out.address,
      "fee": self.fee,
      "amountIn": token_in.to_raw(amount_in),
      "sqrtPriceLimitX96": 0
    }
    bid_amount = self.quoter.functions.quoteExactInputSingle(quote_params).call()
    return token_out.to_human(bid_amount[0])

  def get_volume_until_price(self, token_in: Token, min_price: float) -> float:
    """
    Calculates volume until min_price, matching the pool's internal swap logic.
    This considers the fee being deducted from input BEFORE the price move.
    """
    state = self.get_pool_state()
    sqrt_price_x96 = state["sqrtPriceX96"]
    current_tick = state["tick"]
    liquidity = state["liquidity"]

    zero_for_one = token_in.address == self.token0.address
    target_sqrt_x96 = self._calculate_target_sqrt_x96(min_price, zero_for_one)

    # Basic check: are we already at/past the price?
    if zero_for_one and target_sqrt_x96 >= sqrt_price_x96: return 0.0
    if not zero_for_one and target_sqrt_x96 <= sqrt_price_x96: return 0.0

    total_input_gross = 0
    current_sqrt_x96 = sqrt_price_x96

    # Fee in parts per million (e.g., 3000 for 0.3%)
    fee_pips = self.fee

    while True:
      if liquidity == 0: break

      next_tick = self._get_next_initialized_tick(current_tick, zero_for_one)
      step_sqrt_x96 = self._tick_to_sqrt_price_x96(next_tick)

      # Determine limit for this step
      if zero_for_one:
        limit_sqrt_x96 = max(step_sqrt_x96, target_sqrt_x96)
      else:
        limit_sqrt_x96 = min(step_sqrt_x96, target_sqrt_x96)

      # 1. Calculate the 'Effective' amount_in needed to reach the limit
      # This is the amount that actually shifts the price (after fees)
      amount_in_effective = self._compute_amount_in(
        liquidity, current_sqrt_x96, limit_sqrt_x96, zero_for_one
      )

      # 2. Scale up to include the fee for this specific step
      # Calculation: gross = effective / (1 - fee)
      # In Solidity terms: amount_in = (amount_in_effective * 1e6) / (1e6 - fee_pips)
      step_amount_in_gross = math.ceil((amount_in_effective * 1_000_000) / (1_000_000 - fee_pips))

      total_input_gross += step_amount_in_gross
      current_sqrt_x96 = limit_sqrt_x96

      # If we reached our target price, we are done
      if current_sqrt_x96 == target_sqrt_x96:
        break

      # If we reached a tick, cross it
      if current_sqrt_x96 == step_sqrt_x96:
        tick_info = self.pool_contract.functions.ticks(next_tick).call()
        liquidity_net = tick_info[1]

        if zero_for_one:
          liquidity -= liquidity_net
        else:
          liquidity += liquidity_net

        current_tick = next_tick - 1 if zero_for_one else next_tick
      else:
        break

    return token_in.to_human(int(total_input_gross))

  def _compute_amount_in(self, liquidity: int, sqrt_a: int, sqrt_b: int, zero_for_one: bool) -> int:
    """Calculates Delta X (token0) or Delta Y (token1) for a price move."""
    if zero_for_one:
      # Delta X = L * (sqrt_a - sqrt_b) / (sqrt_a * sqrt_b)
      num = (liquidity << 96) * abs(sqrt_a - sqrt_b)
      den = sqrt_a * sqrt_b
      return num // den
    else:
      # Delta Y = L * (sqrt_b - sqrt_a)
      return (liquidity * abs(sqrt_b - sqrt_a)) >> 96

  def _calculate_target_sqrt_x96(self, min_price: float, zero_for_one: bool) -> int:
    # Adjustment for decimal differences: price = (1.0001^tick) * 10^(d0-d1)
    decimal_adj = 10 ** (self.token1.decimals - self.token0.decimals)

    if zero_for_one:
      # Price provided is token1 per token0
      price_ratio = min_price / decimal_adj
    else:
      # Input is token1, price provided is token0 per token1. Invert for pool ratio.
      price_ratio = (1 / min_price) / decimal_adj

    return int(math.sqrt(price_ratio) * (2 ** 96))

  def _tick_to_sqrt_price_x96(self, tick: int) -> int:
    return int((1.0001 ** (tick / 2)) * (2 ** 96))

  def _get_next_initialized_tick(self, current_tick: int, zero_for_one: bool) -> int:
    """Finds the next initialized tick using the TickBitmap contract function."""
    compressed = current_tick // self.tick_spacing

    if zero_for_one:
      # Moving down (selling token0)
      word_pos = (compressed - 1) >> 8
      bit_pos = (compressed - 1) & 0xFF
      for _ in range(100):  # Limit iterations for performance
        bitmap = self.pool_contract.functions.tickBitmap(word_pos).call()
        mask = (1 << (bit_pos + 1)) - 1
        masked = bitmap & mask
        if masked:
          next_bit = masked.bit_length() - 1
          return ((word_pos << 8) + next_bit) * self.tick_spacing
        word_pos -= 1
        bit_pos = 255
      return -887272  # Minimum tick boundary
    else:
      # Moving up (selling token1)
      word_pos = (compressed + 1) >> 8
      bit_pos = (compressed + 1) & 0xFF
      for _ in range(100):
        bitmap = self.pool_contract.functions.tickBitmap(word_pos).call()
        mask = ~((1 << bit_pos) - 1) & ((1 << 256) - 1)
        masked = bitmap & mask
        if masked:
          lsb = masked & -masked
          next_bit = lsb.bit_length() - 1
          return ((word_pos << 8) + next_bit) * self.tick_spacing
        word_pos += 1
        bit_pos = 0
      return 887272  # Maximum tick boundary

  def get_token(self, token: Tokens) -> Token:
    if token.to_address(self.chain_id) == self.token0.address:
      return self.token0
    elif token.to_address(self.chain_id) == self.token1.address:
      return self.token1
    else:
      raise ValueError(f"Token {token} not found in pool")

  def get_opposite_token(self, token: Tokens) -> Token:
    if token.to_address(self.chain_id) == self.token0.address:
      return self.token1
    elif token.to_address(self.chain_id) == self.token1.address:
      return self.token0
    else:
      raise ValueError(f"Token {token} not found in pool")

  async def swap(self, token_in: Tokens, amount_in: float, eth_price: float, min_amount_out: float = None) -> str:
    gas, tx = self.prepare_order_tx(token_in, amount_in, min_amount_out)
    costs = gas * eth_price
    self.logger.info(f"Swap costs: {costs:.2}$")
    signed: SignedTransaction = self.w3.eth.account.sign_transaction(tx, self.wallet.key)
    tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
    return tx_hash.hex()

  async def get_swap_costs(self, token_in: Tokens, amount_in: float, min_amount_out: float, eth_price: float,
                           static=False) -> float:

    if static:
      # 1. Get current Base Fee
      latest_block = self.w3.eth.get_block('latest')
      base_fee = latest_block['baseFeePerGas']

      # 2. Your manual Priority Fee (0.01 Gwei)
      prio_fee = self.w3.to_wei(0.01, 'gwei')

      # 3. Calculate your specific Max Fee per Gas
      # We add a 12.5% buffer to the base fee to ensure the tx remains
      # valid even if the base fee rises in the next block.
      max_fee_per_gas = int(base_fee * 1.125) + prio_fee

      # 4. Calculate total cost using your precise gas_used
      gas_used = 280493
      gas_in_wei = gas_used * max_fee_per_gas

      # 5. Convert and return USD
      gas_costs_eth = self.w3.from_wei(gas_in_wei, "ether")
      return float(gas_costs_eth) * eth_price
    else:
      gas, _ = self.prepare_order_tx(token_in, amount_in, min_amount_out)
      return gas * eth_price

  def prepare_order_tx(self, token_in: Tokens, amount_in: float, min_amount_out: float):
    input_token = self.get_token(token_in)
    output_token = self.get_opposite_token(token_in)
    codec = RouterCodec(self.w3)
    path = [
      input_token.address,
      self.fee,
      output_token.address,
    ]
    # p2_amount, p2_expiration, p2_nonce = self.permit2.functions.allowance(
    #   self.wallet.address,
    #   input_token.contract.address,
    #   self.universal_router.address
    # ).call()
    # data, signable_message = codec.create_permit2_signable_message(
    #   input_token.contract.address,
    #   Wei(input_token.to_raw(amount_in)),  # max = 2**160 - 1
    #   codec.get_default_expiration(),
    #   p2_nonce,  # Permit2 nonce, see below how to get it
    #   self.universal_router.address,  # The UR checksum address
    #   codec.get_default_deadline(),
    #   self.chain_id,  # chain id
    # )
    # .permit2_permit(data, self.wallet.sign_message(signable_message))

    if min_amount_out is None:
      quote_params = {
        "tokenIn": input_token.address,
        "tokenOut": output_token.address,
        "fee": self.fee,
        "amountIn": input_token.to_raw(amount_in),
        "sqrtPriceLimitX96": 0
      }
      bid_amount = self.quoter.functions.quoteExactInputSingle(quote_params).call()
      min_amount_out = int(bid_amount[0] * 0.9999)
    else:
      min_amount_out = output_token.to_raw(min_amount_out)

    # 1. Fetch current network conditions
    latest_block = self.w3.eth.get_block('latest')
    base_fee = latest_block['baseFeePerGas']

    # 2. Define your tiny priority fee (0.01 Gwei)
    prio_fee = self.w3.to_wei(0.01, 'gwei')

    # Standard practice is (Base Fee * 2) + Prio Fee to handle block volatility
    # If you want to be strictly cheap, use (Base Fee + Prio Fee), but it might fail if base fee rises 1%
    max_fee = int(base_fee * 1.2) + prio_fee

    tx = (
      codec.encode
      .chain()
      .v3_swap_exact_in(
        function_recipient=FunctionRecipient.SENDER,
        amount_in=input_token.to_raw(amount_in),
        amount_out_min=min_amount_out,
        path=path,
        custom_recipient=None,
        payer_is_sender=True
      )
      .build_transaction(
        sender=self.wallet.address,
        value=0,
        nonce=self.w3.eth.get_transaction_count(self.wallet.address),
        chain_id=self.chain_id,
        deadline=codec.get_default_deadline(),
        ur_address=self.universal_router.address
      )
    )
    tx['maxFeePerGas'] = max_fee
    tx['maxPriorityFeePerGas'] = prio_fee

    current_base_fee = self.w3.eth.get_block('latest')['baseFeePerGas']

    # This is what you will likely actually pay
    estimated_actual_cost = self.w3.from_wei(tx['gas'] * (current_base_fee + prio_fee), "ether")

    return float(estimated_actual_cost), tx
