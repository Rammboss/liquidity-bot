import asyncio
import os

import dotenv
from web3 import Web3

from app.exchanges.Coinbase.Coinbase import Coinbase
from app.exchanges.UniswapV3 import UniswapV3
from blockchain.Network import Network
from blockchain.Token import Token, Tokens
from blockchain.uniswap.Pool import Pool
from common.AccountManager import AccountManager
from common.logger import get_logger
from main import COINBASE_EURC_USDC_TICKER, EURO_USDC_UNI_V3_POOL_ADDRESS
from services.UniswapArbitrageAnalyzer import UniswapArbitrageAnalyzer

dotenv.load_dotenv()


def get_average_price(book_side, target_quantity, limit_price, is_ask=True):
  """
  Berechnet den VWAP für eine Zielmenge.
  book_side: order_book.pricebook.asks oder bids
  limit_price: Der Preis von Uniswap (unsere Schmerzgrenze)
  """
  total_volume = 0.0
  total_cost = 0.0

  for entry in book_side:
    price = float(entry.price)
    size = float(entry.size)

    # Check: Ist der Preis überhaupt noch profitabel gegenüber Uni?
    if is_ask and price >= limit_price:
      break  # Kauf zu teuer
    if not is_ask and price <= limit_price:
      break  # Verkauf zu günstig

    # Wie viel nehmen wir von dieser Position?
    remaining_needed = target_quantity - total_volume
    take_amount = min(size, remaining_needed)

    total_volume += take_amount
    total_cost += take_amount * price

    if total_volume >= target_quantity:
      break

  if total_volume == 0:
    return None, 0
  return (total_cost / total_volume), total_volume


async def main():
  logger = get_logger()
  logger.info("Test started")
  coinbase = Coinbase("EURC/USDC", Tokens.EURC, Tokens.USDC)
  pool = Pool(EURO_USDC_UNI_V3_POOL_ADDRESS)
  # pool_swap_fees = await pool.get_swap_costs(pool.token1.token, 1, 0)
  order = coinbase.create_order("buy", "limit", 1, 0.99)
  test1 = await  coinbase.wait_order_filled(order['id'], 120)
  test2 = await pool.swap(Tokens.EURC, 2417.118612910428 , 2800)

  test = await coinbase.get_withdrawal_fees(Tokens.ETH)
  logger.info(test)

  # task = CoinbaseWithdrawalTask(
  #   Tokens.USDC,
  #   None,
  #   10.123456789
  # )
  # await task.run()
  coinbase_uniswap_arbitrage_analyzer = UniswapArbitrageAnalyzer(COINBASE_EURC_USDC_TICKER,
                                                                 EURO_USDC_UNI_V3_POOL_ADDRESS,
                                                                 Tokens.EURC,
                                                                 Tokens.USDC)
  # coinbase_uniswap_arbitrage_analyzer.balance_reorg_needed(token_needed_wallet=Tokens.USDC, amount_needed_wallet=2996, token_needed_coinbase=Tokens.EURC,
  #                                                          amount_needed_coinbase=2546.44)

  account_manager = AccountManager(coinbase)
  w3 = Web3(Web3.HTTPProvider(os.getenv("RPC_URL")))

  wallet_transfer_amount = 10 #account_manager.get_wallet_balances().get(Tokens.EURC)
  euroc = Token(Tokens.EURC)
  deposit_address = coinbase.get_deposit_addresses(Tokens.EURC, Network.ETH)
  tx = euroc.contract.functions.transfer(
    deposit_address,
    euroc.to_raw(wallet_transfer_amount)
  ).build_transaction({"chainId": w3.eth.chain_id, "from": account_manager.wallet.address})

  gas_costs = w3.eth.estimate_gas(tx) * w3.eth.gas_price
  eth_price = 1950
  logger.info(f"Gas costs for transfer: {w3.from_wei(gas_costs, 'ether'):.18f} ETH = {w3.from_wei(gas_costs, 'ether') * eth_price:.2f} USDC")
  signed_tx = w3.eth.account.sign_transaction(tx, account_manager.wallet.key)
  w3.eth.send_raw_transaction(signed_tx.rawTransaction)

  test = w3.eth.syncing
  target_qty = 5000  # Die Menge, die du bewegen willst (z.B. 5k EURC)
  product = coinbase.get_product_id(Tokens.EURC, Tokens.USDC)

  eurc_usdc_pool = UniswapV3(chain="ethereum", fee_tier=500)

  while True:
    order_book = coinbase.get_product_book(product.product_id)

    ask_coinbase = order_book.pricebook.asks[0]
    bid_coinbase = order_book.pricebook.bids[0]

    ask_uni = eurc_usdc_pool.get_ask()
    bid_uni = eurc_usdc_pool.get_bid()

    profit_a = bid_uni - float(ask_coinbase.price)

    # Arbitrage Check: Weg 2 (Uniswap -> Coinbase)
    # Wir kaufen bei Uni zum Ask und verkaufen bei Coinbase zum Bid
    profit_b = float(bid_coinbase.price) - ask_uni
    target_profit = 1.0  # Dein Ziel in USDC

    if profit_a > 0:
      avg_price_cb, actual_vol = get_average_price(order_book.pricebook.asks, target_qty, bid_uni, is_ask=True)
      if avg_price_cb:
        real_profit_per_unit = bid_uni - avg_price_cb
        total_profit = real_profit_per_unit * actual_vol
        logger.info(f"VWAP Kauf Coinbase: {avg_price_cb:.6f} | Volumen: {actual_vol}")
        logger.info(f"Realer Profit nach Orderbuch-Tiefe: {total_profit:.2f} USDC")
      else:
        logger.warning("Arbitrage durch Orderbuch-Tiefe nicht mehr profitabel!")

      # max_volume = float(ask_coinbase.size)
      # # Szenario A: Kauf Coinbase, Verkauf Uni
      # required_volume_for_1_dollar = target_profit / profit_a
      # logger.info(f"Um {target_profit}$ Profit zu machen, musst du {required_volume_for_1_dollar:.4f} EURC bewegen.")
      # if required_volume_for_1_dollar > max_volume:
      #   logger.warning("Warnung: Das Orderbuch auf Coinbase hat nicht genug Volumen für 1$ Profit!")
      # logger.info(
      #   f"Arbitrage gefunden! Kauf Coinbase, Verkauf Uni. Profit/Unit: {profit_a} USDC. Max Volume: {max_volume}")
    if profit_b > 0:
      avg_price_cb, actual_vol = get_average_price(order_book.pricebook.bids, target_qty, ask_uni, is_ask=False)

      if avg_price_cb:
        real_profit_per_unit = avg_price_cb - ask_uni
        total_profit = real_profit_per_unit * actual_vol
        logger.info(f"VWAP Verkauf Coinbase: {avg_price_cb:.6f} | Volumen: {actual_vol}")
        logger.info(f"Realer Profit nach Orderbuch-Tiefe: {total_profit:.2f} USDC")

      # max_volume = float(bid_coinbase.size)
      #
      # # Szenario B: Kauf Uni, Verkauf Coinbase
      # required_volume_for_1_dollar = target_profit / profit_b
      # logger.info(f"Um {target_profit}$ Profit zu machen, musst du {required_volume_for_1_dollar:.4f} EURC bewegen.")
      #
      # if required_volume_for_1_dollar > max_volume:
      #   logger.warning("Warnung: Das Orderbuch auf Coinbase hat nicht genug Volumen für 1$ Profit!")
      #
      # logger.info(
      #   f"Arbitrage gefunden! Kauf Uni, Verkauf Coinbase. Profit/Unit: {profit_b} USDC. Max Volume: {max_volume}")

    await asyncio.sleep(10)


if __name__ == "__main__":
  asyncio.run(main())
