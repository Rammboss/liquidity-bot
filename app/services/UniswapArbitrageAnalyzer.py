import asyncio
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import dotenv
from web3 import Web3

from blockchain.Network import Network
from blockchain.Token import Token, Tokens
from blockchain.WalletService import WalletService
from blockchain.uniswap.Pool import Pool
from common.AccountManager import AccountManager
from common.TelegramServices import TelegramServices
from common.logger import get_logger
from exchanges.Coinbase.Coinbase import Coinbase
from exchanges.UniswapV3 import UniswapV3
from execution.tasks.ArbitrageExecuteTask import ArbitrageExecuteTask
from execution.tasks.CoinbaseWithdrawalTask import CoinbaseWithdrawalTask
from execution.tasks.WalletWithdrawalTask import WalletWithdrawalTask
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
    # Beispiel: Nur Swaps über 100 USDC sind relevant
    return self.swap_amount > 100.0


class UniswapArbitrageAnalyzer:
  CB_FEE_RATE = 0.00001
  DEFAULT_USAGE_RATIO = 0.95
  REPORT_INTERVAL_SECONDS = 300

  def __init__(
      self,
      starting_date: datetime,
      starting_balance_eth: float,
      starting_balance_eurc: float,
      starting_balance_usdc: float,
      target_qty: float,
      coinbase_product_id, uni_pool_address,
      token0: Tokens,
      token1: Tokens,
      executor: Executor,
      runtime_state=None
  ):
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
    self.target_qty = target_qty
    self.telegram = TelegramServices(os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID"))
    self.starting_date = starting_date
    self.starting_balance_eth = starting_balance_eth
    self.starting_balance_eurc = starting_balance_eurc
    self.starting_balance_usdc = starting_balance_usdc
    self.runtime_state = runtime_state
    self._last_report_ts = 0.0

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
    Berechnet den VWAP für die Zielmenge (target_quantity) und liefert zusätzlich
    das gesamte ausführbare Volumen am Book bis zum Limitpreis.

    Returns:
      tuple[float | None, float, float]:
        - average_price_for_target: VWAP der (Teil-)Ausführung für target_quantity
        - matched_volume_for_target: tatsächlich genutztes Volumen für target_quantity
        - total_volume_until_limit: gesamtes verfügbares Volumen bis limit_price (unabhängig vom target)
    """
    matched_volume_for_target = 0.0
    total_cost_for_target = 0.0
    total_volume_until_limit = 0.0
    remaining_qty = max(target_quantity, 0.0)

    for entry in book_side:
      price = float(entry.price)
      size = float(entry.size)

      # Profitability-Check gegen das Limit
      if is_ask and price >= limit_price:
        break
      if not is_ask and price <= limit_price:
        break

      total_volume_until_limit += size

      if remaining_qty <= 0:
        continue

      take_qty = min(size, remaining_qty)
      matched_volume_for_target += take_qty
      total_cost_for_target += take_qty * price
      remaining_qty -= take_qty

    if matched_volume_for_target == 0:
      return None, 0.0, total_volume_until_limit

    average_price_for_target = total_cost_for_target / matched_volume_for_target
    return average_price_for_target, matched_volume_for_target, total_volume_until_limit

  async def run(self):
    self.logger.info("Starting Uniswap Arbitrage Analyzer...")
    wallet_balances = self.account_manager.get_wallet_balances()
    coinbase_balances = self.account_manager.get_coinbase_balances()
    total = self.account_manager.get_total_balances()
    self.logger.info(f"Wallet: {wallet_balances}")
    self.logger.info(f"Coinbase: {coinbase_balances}")
    self.logger.info(f"Total: {total}")

    order_book = self.coinbase.get_product_book(self.coinbase.product.product_id)
    ask_price = float(order_book.pricebook.asks[0].price)
    result = self.calculate_rebalance(total.get(Tokens.USDC), total.get(Tokens.EURC), ask_price)
    eth_price = self.coinbase.get_eth_price()

    total_profit_usdc, apr, runtime_delta = self._compute_performance_metrics(
      total_balances=total,
      eurc_price=ask_price,
      eth_price=eth_price
    )
    self._log_performance_summary(total, total_profit_usdc, apr, runtime_delta)
    self.logger.info(f"Rebalance Analysis: {result}")

    while True:
      try:
        if self.runtime_state and self.runtime_state.is_sleep_mode():
          await asyncio.sleep(1)
          continue

        if len(self.executor.queue) > 0:
          self.logger.info(
            f"Executor queue has {len(self.executor.queue)} tasks. Waiting before next analysis...")
          await asyncio.sleep(10)
          continue

        order_book = self.coinbase.get_product_book(self.coinbase.product.product_id)
        ask_coinbase = order_book.pricebook.asks[0]
        bid_coinbase = order_book.pricebook.bids[0]

        ask_uni = self.pool.get_ask(self.token1, self.target_qty) / self.target_qty
        bid_uni = self.pool.get_bid(self.token0, self.target_qty) / self.target_qty

        profit_a = bid_uni - float(ask_coinbase.price)
        profit_b = float(bid_coinbase.price) - ask_uni

        await self._send_periodic_report_if_due(
          total_balances=self.account_manager.get_total_balances(),
          eurc_price=float(ask_coinbase.price)
        )

        if profit_a > 0:
          await self._process_opportunity(
            side="A",
            profit_raw=profit_a,
            target_qty=self.target_qty,
            entry_price=bid_uni,  # Preis auf der Gegenseite
            order_book_side=order_book.pricebook.asks,
            is_cb_buy=True
          )
        elif profit_b > 0 >= profit_a:
          await self._process_opportunity(
            side="B",
            profit_raw=profit_b,
            target_qty=self.target_qty,
            entry_price=ask_uni,
            order_book_side=order_book.pricebook.bids,
            is_cb_buy=False
          )

        await asyncio.sleep(12)
      except Exception as e:
        self.logger.error(f"Error in main loop: {e}")
        await asyncio.sleep(10)

  async def _process_opportunity(self, side: str, profit_raw: float, target_qty: float,
                                 entry_price: float, order_book_side: list, is_cb_buy: bool
                                 ):
    t_needed_wallet, t_needed_cb = self._get_needed_tokens(is_cb_buy)

    # 1. Balances & Amounts (single fetch to reduce REST/Node calls per loop)
    total_balances, wallet_balances, coinbase_balances = self._get_balance_snapshot()
    usdc_balance_total = total_balances.get(Tokens.USDC, 0.0)
    eurc_balance_total = total_balances.get(Tokens.EURC, 0.0)

    usage = self.DEFAULT_USAGE_RATIO
    cb_rebasing_needed, wallet_rebasing_needed = self.check_rebalance(
      eurc_balance_total=eurc_balance_total,
      is_cb_buy=is_cb_buy,
      usdc_balance_total=usdc_balance_total,
      t_needed_wallet=t_needed_wallet,
      t_needed_cb=t_needed_cb,
      usage=usage,
      wallet_balances=wallet_balances,
      coinbase_balances=coinbase_balances
    )
    buy_balance = min(target_qty, usdc_balance_total * usage)
    target_quantity = buy_balance if is_cb_buy else min(target_qty, eurc_balance_total * usage)
    avg_price_cb, matched_volume, cb_available_volume = self.get_average_price(
      book_side=order_book_side,
      limit_price=entry_price,
      is_ask=is_cb_buy,
      target_quantity=target_quantity
    )

    if not avg_price_cb or matched_volume <= 0:
      return

    # Ergebnis-Menge (Outcome) berechnen
    buy_outcome = buy_balance / (avg_price_cb if is_cb_buy else entry_price)

    # 2. Kostenkalkulation (Zentralisiert)
    cb_withdrawal_fee = await self.coinbase.estimate_withdrawal_fees()
    eth_price = self.coinbase.get_eth_price()
    pool_swap_fees = await self.pool.get_swap_costs(self.token0.token, buy_outcome, 0, eth_price, True)
    self.logger.info(f"Swap fees:~{pool_swap_fees}$")
    if wallet_balances.get(Tokens.EURC, 0.0) < 1:
      existing_token_on_wallet = Tokens.USDC
    else:
      existing_token_on_wallet = Tokens.EURC
    wallet_transfer_fees = await self.wallet_service.get_transfer_costs(
      self.pool.get_token(existing_token_on_wallet), eth_price)
    transfer_costs = cb_withdrawal_fee + wallet_transfer_fees if cb_rebasing_needed or wallet_rebasing_needed else 0
    trading_base_amount = buy_balance if is_cb_buy else buy_outcome
    trading_costs = (trading_base_amount * self.CB_FEE_RATE) + pool_swap_fees + transfer_costs

    break_even = trading_costs / profit_raw

    # Real Profit: Was kommt am Ende raus minus was haben wir reingesteckt minus Kosten
    sell_price = entry_price if is_cb_buy else avg_price_cb
    real_profit = (buy_outcome * sell_price - buy_balance) - trading_costs

    liquidity_reference_price = entry_price if is_cb_buy else avg_price_cb
    liquidity_pool = self.pool.get_volume_until_price(
      self.pool.get_token(t_needed_wallet),
      liquidity_reference_price
    )

    self._log_opportunity_summary(
      side=side,
      is_cb_buy=is_cb_buy,
      t_needed_wallet=t_needed_wallet,
      buy_balance=buy_balance,
      avg_price_cb=avg_price_cb,
      entry_price=entry_price,
      buy_outcome=buy_outcome,
      trading_costs=trading_costs,
      break_even=break_even,
      real_profit=real_profit,
      liquidity_pool=liquidity_pool,
      cb_available_volume=cb_available_volume
    )

    if real_profit <= 0:
      return

    if cb_rebasing_needed or wallet_rebasing_needed:
      self._enqueue_rebalance_tasks(
        wallet_rebasing_needed=wallet_rebasing_needed,
        cb_rebasing_needed=cb_rebasing_needed,
        t_needed_cb=t_needed_cb,
        t_needed_wallet=t_needed_wallet,
        eth_price=eth_price,
        wallet_balances=wallet_balances,
        coinbase_balances=coinbase_balances
      )
    else:
      expected_quote_out = buy_outcome * (entry_price if is_cb_buy else avg_price_cb)
      self.logger.info(
        f"Add [ArbitrageExecuteTask] to queue | side={side} | in={buy_balance:.2f} USDC | "
        f"out={buy_outcome:.4f} EURC | quote_out={expected_quote_out:.2f} USDC | "
        f"profit={real_profit:.2f} USDC | pool_liquidity={liquidity_pool:.4f} {t_needed_wallet.name} | "
        f"cb_volume={cb_available_volume:.4f}"
      )
      self.executor.queue.append(ArbitrageExecuteTask(
        coinbase=self.coinbase,
        pool=self.pool,
        wallet_service=self.wallet_service,
        account_manager=self.account_manager,
        sell_coinbase_buy_uni=not is_cb_buy,
        t1_stat_amount=buy_balance,
        t1_expected_outcome=buy_outcome,
        t2_expected_outcome=expected_quote_out,
        cb_price=avg_price_cb if is_cb_buy else entry_price,
        pool_liquidity=liquidity_pool,
        cb_available_volume=cb_available_volume,
        eth_price=eth_price
      ))

  def check_rebalance(self, eurc_balance_total: float | Any, is_cb_buy: bool, usdc_balance_total: float | Any,
                      t_needed_wallet: Tokens, t_needed_cb: Tokens, usage: float,
                      wallet_balances: dict[Tokens, float], coinbase_balances: dict[Tokens, float]
                      ) -> tuple[bool, bool]:
    cb_rebasing_needed = False
    wallet_rebasing_needed = False

    if is_cb_buy:
      usdc_balance_cb = coinbase_balances.get(Tokens.USDC, 0.0)
      if self._is_below_usage_threshold(usdc_balance_cb, usdc_balance_total, usage):
        percentage_usdc_on_coinbase = self._safe_ratio(usdc_balance_cb, usdc_balance_total)
        self._log_rebalance_warning(percentage_usdc_on_coinbase, t_needed_cb)
        wallet_rebasing_needed = True

      euroc_balance_wallet = wallet_balances.get(Tokens.EURC, 0.0)
      if self._is_below_usage_threshold(euroc_balance_wallet, eurc_balance_total, usage):
        percentage_eurc_on_wallet = self._safe_ratio(euroc_balance_wallet, eurc_balance_total)
        self._log_rebalance_warning(percentage_eurc_on_wallet, t_needed_wallet, location="Wallet")
        cb_rebasing_needed = True
    else:
      eurc_balance_cb = coinbase_balances.get(Tokens.EURC, 0.0)
      if self._is_below_usage_threshold(eurc_balance_cb, eurc_balance_total, usage):
        percentage_eurc_on_coinbase = self._safe_ratio(eurc_balance_cb, eurc_balance_total)
        self._log_rebalance_warning(percentage_eurc_on_coinbase, t_needed_cb)
        wallet_rebasing_needed = True

      usdc_balance_wallet = wallet_balances.get(Tokens.USDC, 0.0)
      if self._is_below_usage_threshold(usdc_balance_wallet, usdc_balance_total, usage):
        percentage_usdc_on_wallet = self._safe_ratio(usdc_balance_wallet, usdc_balance_total)
        self._log_rebalance_warning(percentage_usdc_on_wallet, t_needed_wallet, location="Wallet")
        cb_rebasing_needed = True

    return cb_rebasing_needed, wallet_rebasing_needed


  def _get_balance_snapshot(self) -> tuple[dict[Tokens, float], dict[Tokens, float], dict[Tokens, float]]:
    """Fetch account balances once to minimize REST/Node calls per arbitrage cycle."""
    total_balances = self.account_manager.get_total_balances()
    wallet_balances = self.account_manager.get_wallet_balances()
    coinbase_balances = self.account_manager.get_coinbase_balances()
    return total_balances, wallet_balances, coinbase_balances

  @staticmethod
  def _get_needed_tokens(is_cb_buy: bool) -> tuple[Tokens, Tokens]:
    return (Tokens.EURC, Tokens.USDC) if is_cb_buy else (Tokens.USDC, Tokens.EURC)

  @staticmethod
  def _safe_ratio(part: float, total: float) -> float:
    if total <= 0:
      return 0.0
    return part / total

  def _is_below_usage_threshold(self, part: float, total: float, usage: float) -> bool:
    return self._safe_ratio(part, total) < usage

  def _log_rebalance_warning(self, ratio: float, token: Tokens, location: str = "Coinbase"):
    self.logger.warning(
      f"Only {ratio:.2%} of total {token.name} is on {location}. Skipping opportunity due to imbalance.")

  def _log_opportunity_summary(self, side: str, is_cb_buy: bool, t_needed_wallet: Tokens,
                               buy_balance: float, avg_price_cb: float, entry_price: float,
                               buy_outcome: float, trading_costs: float, break_even: float,
                               real_profit: float, liquidity_pool: float, cb_available_volume: float):
    self.logger.info(f"[{side}] Break-even: {trading_costs:.2f} EURC, Min Trade: {break_even:.2f} EURC")
    self.logger.info(f"Liquidity Pool: {liquidity_pool:.2f} {t_needed_wallet.name}")
    self.logger.info(f"Coinbase Available Volume: {cb_available_volume:.4f}")

    if is_cb_buy:
      self.logger.info(f"Coinbase - Buy {buy_balance:.2f}$ ---{avg_price_cb:.6f}€---> {buy_outcome:.2f}€")
      self.logger.info(
        f"Uniswap - Sell {buy_outcome:.2f}€ ---{entry_price:.6f}$---> {buy_outcome * entry_price:.2f}$")
    else:
      self.logger.info(f"Uniswap - Buy: {buy_balance:.2f}$ ---{entry_price:.6f}€---> {buy_outcome:.2f}€")
      self.logger.info(
        f"Coinbase - Sell {buy_outcome:.2f}€ ---{avg_price_cb:.6f}$---> {buy_outcome * avg_price_cb:.2f}$")

    self.logger.info(f"Profit (incl. costs): {real_profit:.2f}$")

  async def _send_periodic_report_if_due(self, total_balances: dict[Tokens, float], eurc_price: float):
    now_ts = datetime.now(timezone.utc).timestamp()
    if now_ts - self._last_report_ts < self.REPORT_INTERVAL_SECONDS:
      return

    eth_price = self.coinbase.get_eth_price()
    total_profit_usdc, apr, runtime_delta = self._compute_performance_metrics(
      total_balances=total_balances,
      eurc_price=eurc_price,
      eth_price=eth_price
    )

    task_snapshot = []
    if self.runtime_state:
      task_snapshot = self.runtime_state.get_task_snapshot()

    self.logger.info(
      f"Periodic Report | Runtime={runtime_delta} | APR={apr:.2f}% | Total Profit={total_profit_usdc:.2f} USDC "
      f"| Tasks={task_snapshot if task_snapshot else '[]'}"
    )

    telegram_message = (
      f"📊 5m Report\n"
      f"Runtime: {runtime_delta}\n"
      f"APR: {apr:.2f}%\n"
      f"Total Profit: {total_profit_usdc:.2f} USDC\n"
      f"Queue: {', '.join(task_snapshot) if task_snapshot else 'empty'}"
    )
    if task_snapshot:
      await self.telegram.native_send(telegram_message)
    else:
      self.logger.info("Skip Telegram periodic report: no events/tasks in queue.")

    self._last_report_ts = now_ts

  def _compute_performance_metrics(self, total_balances: dict[Tokens, float], eurc_price: float,
                                   eth_price: float) -> tuple[float, float, str]:
    current_date = datetime.now(timezone.utc)
    if self.starting_date.tzinfo is None:
      starting_date_aware = self.starting_date.replace(tzinfo=timezone.utc)
    else:
      starting_date_aware = self.starting_date

    runtime_delta = current_date - starting_date_aware
    runtime_seconds = runtime_delta.total_seconds()

    profit_eth = total_balances.get(Tokens.ETH, 0.0) - self.starting_balance_eth
    profit_eurc = total_balances.get(Tokens.EURC, 0.0) - self.starting_balance_eurc
    profit_usdc = total_balances.get(Tokens.USDC, 0.0) - self.starting_balance_usdc

    total_profit_usdc = profit_eth * eth_price + profit_eurc * eurc_price + profit_usdc

    starting_total_usdc = (
      self.starting_balance_eth * eth_price +
      self.starting_balance_eurc * eurc_price +
      self.starting_balance_usdc
    )

    if runtime_seconds <= 0 or starting_total_usdc <= 0:
      return total_profit_usdc, 0.0, str(runtime_delta)

    seconds_in_year = 365 * 24 * 60 * 60
    apr = (total_profit_usdc / starting_total_usdc) * (seconds_in_year / runtime_seconds) * 100
    return total_profit_usdc, apr, str(runtime_delta)

  def _log_performance_summary(self, total_balances: dict[Tokens, float], total_profit_usdc: float,
                               apr: float, runtime_delta: str):
    self.logger.info(f"Total profit: {total_profit_usdc}$")
    self.logger.info(f"balances @start: {self.starting_balance_eurc}€ | {self.starting_balance_usdc}$")
    self.logger.info(
      f"balances now: {total_balances.get(Tokens.EURC, 0.0)}€ | {total_balances.get(Tokens.USDC, 0.0)}$")
    self.logger.info(f"Runtime: {runtime_delta}")
    self.logger.info(f"Current APR: {apr:.2f}%")

  def _has_queued_task(self, task_type: type) -> bool:
    return any(isinstance(task, task_type) for task in self.executor.queue)

  def _enqueue_rebalance_tasks(self, wallet_rebasing_needed: bool, cb_rebasing_needed: bool,
                               t_needed_cb: Tokens, t_needed_wallet: Tokens, eth_price: float,
                               wallet_balances: dict[Tokens, float], coinbase_balances: dict[Tokens, float]):
    if wallet_rebasing_needed and not self._has_queued_task(WalletWithdrawalTask):
      wallet_bal = wallet_balances.get(t_needed_cb, 0.0)
      if wallet_bal < 100:
        self.logger.warning(
          f"Wallet balacne is too small: {wallet_bal}{t_needed_wallet.name}, check the trigger logik here ")
      dep_addr = self.coinbase.get_deposit_addresses(t_needed_cb, Network.ETH)
      self.logger.info(f"Add [WalletWithdrawalTask] to queue | token={t_needed_cb.name} | amount={wallet_bal:.4f}")
      self.executor.queue.append(
        WalletWithdrawalTask(
          wallet_service=self.wallet_service,
          send_token=self.pool.get_token(t_needed_cb),
          destination=dep_addr,
          eth_price=eth_price,
          coinbase=self.coinbase,
          amount=wallet_bal
        ))

    if cb_rebasing_needed and not self._has_queued_task(CoinbaseWithdrawalTask):
      cb_bal = coinbase_balances.get(t_needed_wallet, 0.0)
      if cb_bal < 100:
        self.logger.warning(
          f"Coinbase balacne is too small: {cb_bal}{t_needed_cb.name}, check the trigger logik here ")
      self.logger.info(f"Add [CoinbaseWithdrawalTask] to queue | token={t_needed_wallet.name} | amount={cb_bal * 0.99:.4f}")
      self.executor.queue.append(
        CoinbaseWithdrawalTask(
          coinbase=self.coinbase,
          wallet_service=self.wallet_service,
          account_manager=self.account_manager,
          token=self.pool.get_token(t_needed_wallet),
          amount=cb_bal * 0.99  # to avoid bad request due invalid balance
        ))
