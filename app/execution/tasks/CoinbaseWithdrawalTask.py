import dotenv
from telegram.constants import ParseMode

from blockchain.Network import Network
from blockchain.Token import Token
from blockchain.WalletService import WalletService
from common.AccountManager import AccountManager
from common.TelegramServices import TelegramServices
from common.logger import get_logger
from exchanges.Coinbase.Coinbase import Coinbase
from execution.BasicTask import BasicTask

dotenv.load_dotenv()


class CoinbaseWithdrawalTask(BasicTask):

  def __init__(
      self,
      coinbase: Coinbase,
      wallet_service: WalletService,
      account_manager: AccountManager,
      token: Token,
      telegram: TelegramServices,
      destination: str = None,
      amount: float = None,
      priority: int = 5
  ):
    super().__init__(priority)
    self.logger = get_logger()
    self.token = token
    self.wallet_service = wallet_service
    self.destination = destination or self.wallet_service.wallet.address
    self.amount = amount

    self.coinbase = coinbase
    self.account_manager = account_manager
    self.telegram = telegram

  async def run(self):
    raw_coinbase_balance = self.account_manager.get_coinbase_balances().get(self.token.token)

    if self.amount is not None:
      withdraw_amount = self.amount
      if raw_coinbase_balance < withdraw_amount:
        raise ValueError(f"Insufficient funds. Have {raw_coinbase_balance}, requested {self.amount} {self.token.symbol}")
    else:
      withdraw_amount = raw_coinbase_balance

    if withdraw_amount <= 0:
      raise ValueError(f"Withdraw amount must be greater than 0 (Balance: {raw_coinbase_balance})")

    self.logger.info(f"Withdrawing {withdraw_amount}{self.token.token.name} from Coinbase to {self.destination}")
    response = self.coinbase.withdrawal(self.token.token, self.destination, withdraw_amount, Network.ETH)
    self.logger.info(f"Withdrawal response: {response}")

    mined = self.wallet_service.wait_till_coins_arrive(self.token)
    if mined:
      self.logger.info(f"Order filled: {response['data']['id']}")
      await self.telegram.native_send(f"Order filled: {response['data']['id']}", ParseMode.HTML)
    else:
      self.logger.warning(f"Order not filled within timeout: {response['data']['id']}")
