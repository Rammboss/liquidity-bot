import os

import dotenv
from web3 import Web3

from blockchain.AbiService import AbiService

dotenv.load_dotenv()

from dataclasses import dataclass


@dataclass
class QuoteResult:
  amountOut: int
  sqrtPriceX96After: int
  initializedTicksCrossed: int
  gasEstimate: int


class QuoterV3:
  def __init__(self, quoter_address):
    self.quoter_address = quoter_address
    self.w3 = Web3(Web3.HTTPProvider(os.getenv("RPC_URL")))
    self.abi_service = AbiService()

    self.contract = self.w3.eth.contract(address=self.quoter_address, abi=self.abi_service.get_abi("QuoterV3"))

  def quote_exact_input_single(self, token_in, token_out, fee, amount_in) -> QuoteResult:
    result = self.contract.functions.quoteExactInputSingle({
      "tokenIn": token_in,
      "tokenOut": token_out,
      "fee": fee,
      "amountIn": amount_in,
      "sqrtPriceLimitX96": 0
    }).call()

    return QuoteResult(
      amountOut=result[0],
      sqrtPriceX96After=result[1],
      initializedTicksCrossed=result[2],
      gasEstimate=result[3]
    )
