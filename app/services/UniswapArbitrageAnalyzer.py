import asyncio
import os
from dataclasses import dataclass
from typing import Any

import dotenv
from web3 import Web3

from blockchain.Network import Network
from blockchain.Token import Token, Tokens
from blockchain.WalletService import WalletService
from blockchain.uniswap.Pool import Pool
from common.AccountManager import AccountManager
from exchanges.Coinbase.Coinbase import Coinbase
from exchanges.UniswapV3 import UniswapV3
from execution.tasks.ArbitrageExecuteTask import ArbitrageExecuteTask
from execution.tasks.CoinbaseWithdrawalTask import CoinbaseWithdrawalTask
from execution.tasks.WalletWithdrawalTask import WalletWithdrawalTask
from common.logger import get_logger
from services.Executor import Executor

dotenv.load_dotenv()


@dataclass(frozen=True)
class RebalanceResult:
  """
  Kapselt das Ergebnis einer Rebalancing-Kalkulation.
  frozen=True verhindert nachträgliche Änderungen (Immutability).
  """
  total_value_usdc: float
  target_value_per_asset: float
  swap_amount: float
  swap_amount_in_eurc: float
  from_token: Tokens
  to_token: Tokens

  @property
  def is_significant(self) -> bool:
    # Beispiel: Nur Swaps über 100.00 USDC sind relevant
    return self.swap_amount > 100.0


class UniswapArbitrageAnalyzer:
  def __init__(self, coinbase_product_id, uni_pool_address, token0: Tokens, token1: Tokens, executor: Executor = None):
    self.logger = get_logger()
    self.w3 = Web3(Web3.HTTPProvider(os.getenv("RPC_URL")))
    self.token0 = Token(token0)
    self.token1 = Token(token1)
    self.coinbase = Coinbase(coinbase_product_id, token0, token1)
    self.pool = Pool(uni_pool_address)
    self.account_manager = AccountManager(self.coinbase)
    self.uniswap_pool = UniswapV3(chain="ethereum", fee_tier=500)
    self.executor = executor
    self.wallet_service = WalletService()

  @staticmethod
  def calculate_rebalance(usdc_amount, eurc_amount, eurc_price_in_usdc) -> RebalanceResult:
    eurc_value_in_usdc = eurc_amount * eurc_price_in_usdc
    total_value_usdc = usdc_amount + eurc_value_in_usdc

    target_value_usdc = total_value_usdc / 2

    usdc_diff = usdc_amount - target_value_usdc
    if usdc_diff > 0:
      from_ = Tokens.USDC
      to = Tokens.EURC
    else:
      from_ = Tokens.EURC
      to = Tokens.USDC

    swap_amount_usdc = abs(usdc_diff)

    return RebalanceResult(
      total_value_usdc=total_value_usdc,
      target_value_per_asset=target_value_usdc,
      swap_amount=swap_amount_usdc,
      swap_amount_in_eurc=swap_amount_usdc / eurc_price_in_usdc,
      from_token=from_,
      to_token=to
    )

  @staticmethod
  def get_average_price(book_side, limit_price, is_ask: bool, target_quantity: float):
    """
    Berechnet den VWAP bis zum Erreichen von target_quantity oder dem limit_price.
    Berücksichtigt Teilausführungen im letzten relevanten Orderbuch-Level.
    """
    total_volume = 0.0
    total_cost = 0.0
    remaining_qty = target_quantity

    for entry in book_side:
      if remaining_qty <= 0:
        break

      price = float(entry.price)
      size = float(entry.size)

      # 1. Profitabilitäts-Check gegen das Limit
      if is_ask and price >= limit_price:
        break
      if not is_ask and price <= limit_price:
        break

      # 2. Bestimme, wie viel wir von diesem Level nehmen
      # Entweder die gesamte Size des Levels oder nur den Rest unserer Zielmenge
      take_qty = min(size, remaining_qty)

      total_volume += take_qty
      total_cost += take_qty * price
      remaining_qty -= take_qty

    if total_volume == 0:
      return None, 0.0

    average_price = total_cost / total_volume
    return average_price, total_volume

  async def run(self):
    self.logger.info("Starting Uniswap Arbitrage Analyzer...")
    target_qty = 3000  # Die Menge, die du bewegen willst (z.B. 5k EURC)

    wallet_balances = self.account_manager.get_wallet_balances()
    coinbase_balances = self.account_manager.get_coinbase_balances()
    total = self.account_manager.get_total_balances()
    self.logger.info(f"Wallet: {wallet_balances}")
    self.logger.info(f"Coinbase: {coinbase_balances}")
    self.logger.info(f"Total: {total}")

    order_book = self.coinbase.get_product_book(self.coinbase.product.product_id)
    result = self.calculate_rebalance(total.get(Tokens.USDC), total.get(Tokens.EURC), float(order_book.pricebook.asks[0].price))
    self.logger.info(f"Rebalance Analysis: {result}")

    while True:
      if len(self.executor.queue) > 0:
        self.logger.info(f"Executor queue has {len(self.executor.queue)} tasks. Waiting before next analysis...")
        await asyncio.sleep(30)
        continue

      order_book = self.coinbase.get_product_book(self.coinbase.product.product_id)
      ask_coinbase = order_book.pricebook.asks[0]
      bid_coinbase = order_book.pricebook.bids[0]

      ask_uni = self.pool.get_ask(self.token1, target_qty) / target_qty
      bid_uni = self.pool.get_bid(self.token0, target_qty) / target_qty

      profit_a = bid_uni - float(ask_coinbase.price)
      profit_b = float(bid_coinbase.price) - ask_uni

      if profit_a > 0:
        await self._process_opportunity(
          side="A",
          profit_raw=profit_a,
          target_qty=target_qty,
          entry_price=bid_uni,  # Preis auf der Gegenseite
          order_book_side=order_book.pricebook.asks,
          is_cb_buy=True
        )

      if profit_b > 0:
        await self._process_opportunity(
          side="B",
          profit_raw=profit_b,
          target_qty=target_qty,
          entry_price=ask_uni,
          order_book_side=order_book.pricebook.bids,
          is_cb_buy=False
        )

      await asyncio.sleep(20)

  async def _process_opportunity(self, side: str, profit_raw: float, target_qty: float,
                                 entry_price: float, order_book_side: list, is_cb_buy: bool
                                 ):
    # 4. Rebalance oder Execution
    # Parameter je nach Richtung festlegen
    t_needed_wallet = Tokens.EURC if is_cb_buy else Tokens.USDC
    t_needed_cb = Tokens.USDC if is_cb_buy else Tokens.EURC

    # 1. Balances & Amounts
    total_balances = self.account_manager.get_total_balances()
    usdc_balance_total = total_balances.get(Tokens.USDC, 0.0)

    eurc_balance_total = total_balances.get(Tokens.EURC, 0.0)

    cb_rebasing_needed, wallet_rebasing_needed = await self.check_rebalance(
      eurc_balance_total=eurc_balance_total,
      is_cb_buy=is_cb_buy,
      usdc_balance_total=usdc_balance_total,
      t_needed_wallet=t_needed_wallet,
      t_needed_cb=t_needed_cb
    )

    buy_balance = min(target_qty, usdc_balance_total * 0.95)
    target_quantity = buy_balance if is_cb_buy else min(target_qty, eurc_balance_total * 0.95)
    avg_price_cb, _ = self.get_average_price(book_side=order_book_side, limit_price=entry_price, is_ask=is_cb_buy, target_quantity=target_quantity)

    if not avg_price_cb:
      return

    # Ergebnis-Menge (Outcome) berechnen
    # Bei Side A: Buy on CB (USDC -> EURC) | Bei Side B: Buy on Uni (USDC -> EURC)
    buy_outcome = buy_balance / (avg_price_cb if is_cb_buy else entry_price)

    # 2. Kostenkalkulation (Zentralisiert)
    CB_FEE_RATE = 0.00001  # 0.001% Taker Fee
    cb_withdrawal_fee = await self.coinbase.get_withdrawal_fees()
    eth_price = self.coinbase.get_eth_price()
    pool_swap_fees = await self.pool.get_swap_costs(self.token0.token, buy_outcome, 0, eth_price, True)
    wallet_transfer_fees = await self.wallet_service.get_transfer_costs(self.pool.get_token(t_needed_cb), eth_price)
    if is_cb_buy:
      trading_costs = (buy_balance * CB_FEE_RATE) + pool_swap_fees + cb_withdrawal_fee + wallet_transfer_fees
    else:
      trading_costs = (buy_outcome * CB_FEE_RATE) + pool_swap_fees + cb_withdrawal_fee + wallet_transfer_fees

    break_even = trading_costs / profit_raw

    # Real Profit: Was kommt am Ende raus minus was haben wir reingesteckt minus Kosten
    sell_price = entry_price if is_cb_buy else avg_price_cb
    real_profit = (buy_outcome * sell_price - buy_balance) - trading_costs

    # 3. Logging
    self.logger.info(f"[{side}] Break-even: {trading_costs:.2f} EURC, Min Trade: {break_even:.2f} EURC")
    if is_cb_buy:
      # Side A: Coinbase Buy -> Uniswap Sell
      self.logger.info(f"Coinbase - Buy {buy_balance:.2f}$ ---{avg_price_cb:.6f}€---> {buy_outcome:.2f}€")
      self.logger.info(f"Uniswap - Sell {buy_outcome:.2f}€ ---{entry_price:.6f}$---> {buy_outcome * entry_price:.2f}$")
    else:
      # Side B: Uniswap Buy -> Coinbase Sell
      self.logger.info(f"Uniswap - Buy: {buy_balance:.2f}$ ---{entry_price:.6f}€---> {buy_outcome:.2f}€")
      self.logger.info(f"Coinbase - Sell {buy_outcome:.2f}€ ---{avg_price_cb:.6f}$---> {buy_outcome * avg_price_cb:.2f}$")

    self.logger.info(f"Profit (incl. costs): {real_profit:.2f}$")

    if real_profit <= 0:
      return

    if cb_rebasing_needed or wallet_rebasing_needed:
      if wallet_rebasing_needed:
        wallet_bal = self.account_manager.get_wallet_balances().get(t_needed_cb)
        dep_addr = self.coinbase.get_deposit_addresses(t_needed_cb, Network.ETH)
        self.executor.queue.append(
          WalletWithdrawalTask(
            wallet_service=self.wallet_service,
            send_token=self.pool.get_token(t_needed_cb),
            destination=dep_addr,
            eth_price=eth_price,
            amount=wallet_bal
          ))
      if cb_rebasing_needed:
        cb_bal = self.account_manager.get_coinbase_balances().get(t_needed_wallet)
        self.executor.queue.append(
          CoinbaseWithdrawalTask(
            coinbase=self.coinbase,
            wallet_service=self.wallet_service,
            account_manager=self.account_manager,
            token=self.pool.get_token(t_needed_wallet),
            amount=cb_bal
          ))
    else:
      self.executor.queue.append(ArbitrageExecuteTask(
        coinbase=self.coinbase,
        pool=self.pool,
        wallet_service=self.wallet_service,
        account_manager=self.account_manager,
        sell_coinbase_buy_uni=not is_cb_buy,
        t1_stat_amount=buy_balance,
        t1_expected_outcome=buy_outcome,
        t2_expected_outcome=buy_outcome * (entry_price if is_cb_buy else avg_price_cb),
        cb_price=avg_price_cb if is_cb_buy else entry_price,
        eth_price=eth_price
      ))

  async def check_rebalance(self, eurc_balance_total: float | Any, is_cb_buy: bool, usdc_balance_total: float | Any,
                            t_needed_wallet: Tokens, t_needed_cb: Tokens
                            ) -> tuple[bool, bool]:
    cb_rebasing_needed = False
    wallet_rebasing_needed = False

    if is_cb_buy:
      usdc_balance_cb = self.account_manager.get_coinbase_balances().get(Tokens.USDC, 0.0)
      percentage_usdc_on_coinbase = (usdc_balance_cb / usdc_balance_total) * 100

      if percentage_usdc_on_coinbase < 95:
        self.logger.warning(f"Only {percentage_usdc_on_coinbase:.2}% of total {t_needed_cb.name} is on Coinbase. Skipping opportunity due to imbalance.")
        wallet_rebasing_needed = True

      euroc_balance_wallet = self.account_manager.get_wallet_balances().get(Tokens.EURC, 0.0)
      percentage_eurc_on_wallet = euroc_balance_wallet / eurc_balance_total
      if percentage_eurc_on_wallet < 95:
        self.logger.warning(f"Only {percentage_eurc_on_wallet:.2}% of total {t_needed_wallet.name} is on Wallet. Skipping opportunity due to imbalance.")
        cb_rebasing_needed = True
    else:
      eurc_balance_cb = self.account_manager.get_coinbase_balances().get(Tokens.EURC, 0.0)
      percentage_eurc_on_coinbase = eurc_balance_cb / eurc_balance_total

      if percentage_eurc_on_coinbase < 95:
        self.logger.warning(f"Only {percentage_eurc_on_coinbase:.2}% of total {t_needed_cb.name} is on Coinbase. Skipping opportunity due to imbalance.")
        wallet_rebasing_needed = True

      usdc_balance_wallet = self.account_manager.get_wallet_balances().get(Tokens.USDC, 0.0)
      percentage_usdc_on_wallet = usdc_balance_wallet / usdc_balance_total
      if percentage_usdc_on_wallet < 95:
        self.logger.warning(f"Only {percentage_usdc_on_wallet:.2}% of total {t_needed_wallet.name} is on Wallet. Skipping opportunity due to imbalance.")
        cb_rebasing_needed = True
    return cb_rebasing_needed, wallet_rebasing_needed
