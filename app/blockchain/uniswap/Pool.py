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
      gas_in_wei = 280493 * self.w3.eth.gas_price
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
    gas_costs = self.w3.from_wei(tx['gas'] * tx['maxFeePerGas'], "ether")

    return float(gas_costs), tx
