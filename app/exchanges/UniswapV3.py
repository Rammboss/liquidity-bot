import asyncio
from typing import Literal, Tuple

from eth_account.datastructures import SignedTransaction
from requests.exceptions import HTTPError
from uniswap_universal_router_decoder import FunctionRecipient, RouterCodec
from web3.exceptions import BlockNotFound, ContractLogicError
from web3.types import TxParams, Wei

from blockchain.Token import Token as Token2, Token, Tokens
from app.Configurations import SLIPPAGE
from app.blockchain.Contract import Contract
from common.errors.PriceExceededError import PriceExceededError
from app.exchanges.IDEX import ChainName, IDEX
from logger import get_logger


class UniswapV3(IDEX):
  def __init__(
      self,
      chain: ChainName,
      fee_tier: Literal[500, 3000, 10000],
      refresh_ticker_by_block: bool = False
  ):
    super().__init__(f"UniswapV3-{chain}-{fee_tier}", chain)
    self.logger = get_logger()
    self.fee_tier = fee_tier

    # --- Contracts ---
    self.quoter = Contract.UNISWAP_V3_QUOTER.get_contract(self.w3, self.chain_id)

    # Start single ticker thread
    self.refresh_ticker_by_block = refresh_ticker_by_block

  async def _update_ticker(self, block_number):
    try:
      # ETH -> USDC
      amount_in = self.w3.to_wei(1, "ether")
      quote_params = {
        "tokenIn": self.eurc_contract.address,
        "tokenOut": self.usdc_contract.address,
        "fee": self.fee_tier,
        "amountIn": amount_in,
        "sqrtPriceLimitX96": 0
      }
      bid_amount = self.quoter.functions.quoteExactInputSingle(quote_params).call()
      bid = bid_amount[0] / (10 ** self.usdc_decimals)

      # USDC -> ETH
      quote_params = {
        "tokenIn": self.usdc_contract.address,
        "tokenOut": self.eurc_contract.address,
        "fee": self.fee_tier,
        "amount": amount_in,
        "sqrtPriceLimitX96": 0
      }
      ask_amount = self.quoter.functions.quoteExactOutputSingle(quote_params).call()

      ask = ask_amount[0] / (10 ** self.usdc_decimals)

      self.ticker.update({
        "bid": float(bid),
        "ask": float(ask),
        "timestamp": int(self.w3.eth.get_block(block_number)["timestamp"]) * 1000
      })

    except ContractLogicError as e:
      self.logger.error(f"Not enough funds on Blockchain {self.name} with chain id {self.chain_id}")
    except BlockNotFound as e:
      self.logger.warning(f"Blockchain {self.name} - Error: {e}")
      await asyncio.sleep(1)
    except HTTPError as e:
      if "Too Many Requests" in e.response.text:
        self.logger.warning(f"To Many Request on {self.name}")
        await asyncio.sleep(25)

  async def prepare_order_tx(self, side: str, type_: str, amount: float, target_price: float) -> Tuple[
    float, TxParams
  ]:
    if side.lower() == "buy":
      token_in = self.w3.to_checksum_address(Tokens.USDC.to_address(self.chain_id))
      token_out = self.w3.to_checksum_address(Tokens.EURC.to_address(self.chain_id))
      amount_in = Token(Tokens.USDC).to_raw(amount)

      min_amount_out = self.quoter.functions.quoteExactInputSingle({
        "tokenIn": token_in,
        "tokenOut": token_out,
        "fee": self.fee_tier,
        "amountIn": amount_in,
        "sqrtPriceLimitX96": 0
      }).call()[0]

      min_amount_out = int(min_amount_out * (1 - SLIPPAGE))

      current_price = amount / float(self.w3.from_wei(min_amount_out, "ether"))

      self.logger.info(
        f"Swap {self.w3.from_wei(amount_in, "mwei")} USDC -> min. {self.w3.from_wei(min_amount_out, "ether"):.18f} "
        f"ETH (Price:{current_price:.2f}) ")

      if current_price > target_price:
        raise PriceExceededError(price=current_price, exchange=self.name)

      codec = RouterCodec(self.w3)
      path = [
        token_in,
        self.fee_tier,
        token_out,
      ]
      p2_amount, p2_expiration, p2_nonce = self.permit2.functions.allowance(
        self.wallet.address,
        self.usdc_contract.address,
        self.universal_router.address
      ).call()
      data, signable_message = codec.create_permit2_signable_message(
        self.usdc_contract.address,
        Wei(amount_in),  # max = 2**160 - 1
        codec.get_default_expiration(),
        p2_nonce,  # Permit2 nonce, see below how to get it
        self.universal_router.address,  # The UR checksum address
        codec.get_default_deadline(),
        self.chain_id,  # chain id
      )
      tx = (
        codec.encode
        .chain()
        .permit2_permit(data, self.wallet.sign_message(signable_message))
        .v3_swap_exact_in(
          FunctionRecipient.ROUTER,
          amount_in,
          min_amount_out,
          path,
          None,
          True
        )
        .unwrap_weth(
          FunctionRecipient.SENDER,
          0
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
    elif side.lower() == "sell":
      token_in = self.w3.to_checksum_address(Tokens.EURC.to_address(self.chain_id))
      token_out = self.w3.to_checksum_address(Tokens.USDC.to_address(self.chain_id))
      amount_in = Token(Tokens.EURC).to_raw(amount)

      min_amount_out = self.quoter.functions.quoteExactInputSingle({
        "tokenIn": token_in,
        "tokenOut": token_out,
        "fee": self.fee_tier,
        "amountIn": amount_in,
        "sqrtPriceLimitX96": 0
      }).call()[0]

      min_amount_out = int(min_amount_out * (1 - SLIPPAGE))

      current_price = float(self.w3.from_wei(min_amount_out, "mwei")) / amount

      self.logger.info(
        f"Swap {self.w3.from_wei(amount_in, "ether"):.18f} ETH -> min. "
        f"{self.w3.from_wei(min_amount_out, "mwei")} USDC (Price:{current_price:.2f})")

      if current_price < target_price:
        raise PriceExceededError(price=current_price, exchange=self.name)

      codec = RouterCodec(self.w3)
      path = [
        token_in,
        self.fee_tier,
        token_out,
      ]
      tx = (
        codec.encode
        .chain()
        .wrap_eth(FunctionRecipient.ROUTER, amount_in)
        .v3_swap_exact_in(
          FunctionRecipient.SENDER,
          amount_in,
          min_amount_out,
          path,
          None,
          False
        )
        .build_transaction(
          sender=self.wallet.address,
          value=amount_in,
          nonce=self.w3.eth.get_transaction_count(self.wallet.address),
          chain_id=self.chain_id,
          deadline=codec.get_default_deadline(),
          ur_address=self.universal_router.address
        )
      )
    else:
      raise ValueError(f"side not allowed: {side}")

    estimated_gas = self.w3.eth.estimate_gas(tx)
    gas_costs = self.w3.from_wei((estimated_gas * self.w3.eth.gas_price), "ether")
    self.logger.info(f"Gas costs: {gas_costs:.18f} ETH - {float(gas_costs) * self.get_bid_ask()['ask']}")

    return float(gas_costs), tx

  async def create_order(self, side: str, type_: str, amount: float, price: float):
    """Perform a UniswapV3 swap."""

    gas, tx = await self.prepare_order_tx(side, type_, amount, price)
    signed: SignedTransaction = self.w3.eth.account.sign_transaction(tx, self.wallet.key)
    tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
    return tx_hash.hex()

  def get_ask(self):
    # USDC -> ETH
    amount_in = Token2(Tokens.EURC).to_raw(1)

    quote_params = {
      "tokenIn": self.usdc_contract.address,
      "tokenOut": self.eurc_contract.address,
      "fee": self.fee_tier,
      "amount": amount_in,
      "sqrtPriceLimitX96": 0
    }
    ask_amount = self.quoter.functions.quoteExactOutputSingle(quote_params).call()

    ask = ask_amount[0] / (10 ** self.usdc_decimals)
    return ask

  def get_bid(self):
    # EUROC -> USDC
    amount_in = Token2(Tokens.EURC).to_raw(1)
    quote_params = {
      "tokenIn": self.eurc_contract.address,
      "tokenOut": self.usdc_contract.address,
      "fee": self.fee_tier,
      "amountIn": amount_in,
      "sqrtPriceLimitX96": 0
    }
    bid_amount = self.quoter.functions.quoteExactInputSingle(quote_params).call()
    bid = bid_amount[0] / (10 ** self.usdc_decimals)
    return bid



