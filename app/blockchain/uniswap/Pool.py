import os

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
    Estimate the maximum `token_in` volume tradable until the pool's marginal
    price reaches `min_price` (token_out per token_in), using pool state,
    liquidity and initialized ticks only (no quoter-orderbook stepping).
    """
    if min_price <= 0:
      raise ValueError("min_price must be greater than 0")

    zero_for_one = token_in.address == self.token0.address
    token_out = self.token1 if zero_for_one else self.token0

    slot0 = self.pool_contract.functions.slot0().call()
    sqrt_price_x96 = int(slot0[0])
    current_tick = int(slot0[1])
    liquidity = int(self.pool_contract.functions.liquidity().call())

    current_price = self._price_token_out_per_token_in(sqrt_price_x96, token_in, token_out)
    if current_price <= min_price:
      return 0.0

    target_sqrt_x96 = self._target_sqrt_price_x96(min_price, zero_for_one)
    q96 = float(2 ** 96)
    sqrt_current = sqrt_price_x96 / q96
    sqrt_target = target_sqrt_x96 / q96

    fee_tier = self.fee / 1_000_000
    fee_factor = 1.0 - fee_tier
    if fee_factor <= 0:
      raise ValueError("Invalid pool fee configuration")

    amount_in_raw_effective = 0.0
    tick_spacing = int(self.pool_contract.functions.tickSpacing().call())

    for _ in range(2000):
      if liquidity <= 0:
        break

      if zero_for_one and sqrt_current <= sqrt_target:
        break
      if (not zero_for_one) and sqrt_current >= sqrt_target:
        break

      next_tick = self._next_initialized_tick(current_tick, tick_spacing, zero_for_one)
      next_tick_sqrt = self._sqrt_ratio_at_tick_x96(next_tick) / q96

      if zero_for_one:
        sqrt_next = max(sqrt_target, next_tick_sqrt)
        amount_step = liquidity * (sqrt_current - sqrt_next) / (sqrt_current * sqrt_next)
      else:
        sqrt_next = min(sqrt_target, next_tick_sqrt)
        amount_step = liquidity * (sqrt_next - sqrt_current)

      if amount_step < 0:
        amount_step = 0

      amount_in_raw_effective += amount_step
      reached_tick_boundary = abs(sqrt_next - next_tick_sqrt) < 1e-18
      sqrt_current = sqrt_next

      if not reached_tick_boundary:
        break

      tick_info = self.pool_contract.functions.ticks(next_tick).call()
      liquidity_net = int(tick_info[1])

      if zero_for_one:
        liquidity -= liquidity_net
        current_tick = next_tick - 1
      else:
        liquidity += liquidity_net
        current_tick = next_tick

    amount_in_raw_gross = amount_in_raw_effective / fee_factor
    return token_in.to_human(int(amount_in_raw_gross))

  def _price_token_out_per_token_in(self, sqrt_price_x96: int, token_in: Token, token_out: Token) -> float:
    q96 = float(2 ** 96)
    sqrt_price = sqrt_price_x96 / q96
    price_token1_per_token0 = (sqrt_price ** 2) * (10 ** (self.token0.decimals - self.token1.decimals))

    if token_in.address == self.token0.address and token_out.address == self.token1.address:
      return price_token1_per_token0

    return 1 / price_token1_per_token0

  def _target_sqrt_price_x96(self, min_price: float, zero_for_one: bool) -> int:
    if zero_for_one:
      price_token1_per_token0 = min_price
    else:
      price_token1_per_token0 = 1 / min_price

    ratio_raw = price_token1_per_token0 * (10 ** (self.token1.decimals - self.token0.decimals))
    return int((ratio_raw ** 0.5) * (2 ** 96))

  def _sqrt_ratio_at_tick_x96(self, tick: int) -> int:
    return int((1.0001 ** (tick / 2)) * (2 ** 96))

  def _next_initialized_tick(self, current_tick: int, tick_spacing: int, zero_for_one: bool) -> int:
    compressed = current_tick // tick_spacing
    if zero_for_one:
      word_pos = (compressed - 1) >> 8
      bit_pos = (compressed - 1) & 0xFF
      for _ in range(4000):
        bitmap = int(self.pool_contract.functions.tickBitmap(word_pos).call())
        mask = (1 << (bit_pos + 1)) - 1
        masked = bitmap & mask
        if masked:
          next_bit = masked.bit_length() - 1
          return ((word_pos << 8) + next_bit) * tick_spacing
        word_pos -= 1
        bit_pos = 255
      return -887272

    word_pos = (compressed + 1) >> 8
    bit_pos = (compressed + 1) & 0xFF
    for _ in range(4000):
      bitmap = int(self.pool_contract.functions.tickBitmap(word_pos).call())
      mask = ~((1 << bit_pos) - 1) & ((1 << 256) - 1)
      masked = bitmap & mask
      if masked:
        lsb = masked & -masked
        next_bit = lsb.bit_length() - 1
        return ((word_pos << 8) + next_bit) * tick_spacing
      word_pos += 1
      bit_pos = 0
    return 887272

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

  async def get_swap_costs(self, token_in: Tokens, amount_in: float, min_amount_out: float, eth_price: float, static=False) -> float:

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
