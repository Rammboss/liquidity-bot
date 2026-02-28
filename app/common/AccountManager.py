import os

import dotenv
from eth_account import Account
from eth_account.signers.local import LocalAccount

from blockchain.Token import Token, Tokens
from exchanges.Coinbase.Coinbase import Coinbase
from common.logger import get_logger

dotenv.load_dotenv()


class AccountManager:
  def __init__(self, coinbase: Coinbase):
    self.logger = get_logger()
    self.coinbase = coinbase
    self.wallet: LocalAccount = Account.from_key(os.getenv("PRIVATE_KEY"))
    self.eurc = Token(Tokens.EURC)
    self.usdc = Token(Tokens.USDC)

  def get_coinbase_balances(self):
    usdc = self.coinbase.get_account_balances(Tokens.USDC, "total")
    eurc = self.coinbase.get_account_balances(Tokens.EURC, "total")
    return {
      Tokens.USDC: usdc,
      Tokens.EURC: eurc
    }

  def get_wallet_balances(self):
    usdc = self.usdc.to_human(self.usdc.contract.functions.balanceOf(self.wallet.address).call())
    eurc = self.eurc.to_human(self.eurc.contract.functions.balanceOf(self.wallet.address).call())
    return {
      Tokens.USDC: usdc,
      Tokens.EURC: eurc
    }

  def get_total_balances(self):
    coinbase_balances = self.get_coinbase_balances()
    wallet_balances = self.get_wallet_balances()
    return {
      Tokens.USDC: coinbase_balances[Tokens.USDC] + wallet_balances[Tokens.USDC],
      Tokens.EURC: coinbase_balances[Tokens.EURC] + wallet_balances[Tokens.EURC]
    }
