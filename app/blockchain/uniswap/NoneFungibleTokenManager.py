import os

import dotenv
from web3 import Web3

from blockchain.AbiService import AbiService

dotenv.load_dotenv()


class NoneFungibleTokenManager:
  def __init__(self, address):
    self.w3 = Web3(Web3.HTTPProvider(os.getenv("RPC_URL")))
    self.abi_service = AbiService()
    self.contract = self.w3.eth.contract(
      address=self.w3.to_checksum_address(address),
      abi=self.abi_service.get_abi("NFPM")
    )

  def get_position(self, token_id):
    return self.contract.functions.positions(token_id).call()
