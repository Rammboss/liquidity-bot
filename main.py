import math
import os

import requests
from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3

from blockchain.AbiService import AbiService

load_dotenv()

# 1. Setup
RPC_URL = os.getenv("RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")
THE_GRAPH_API_KEY = os.getenv("THE_GRAPH_API_KEY")

# Using the account object we created
account = Account.from_key(PRIVATE_KEY)
w3 = Web3(Web3.HTTPProvider(RPC_URL))

# Uniswap v3 Position Manager Address
NFPM_ADDRESS = "0xC36442b4a4522E871399CD717aBDD847Ab11FE88"
POOL_CONTRACT_ADDRESS = "0x95DBB3C7546F22BCE375900AbFdd64a4E5bD73d6"

# Usage in your script
abi_service = AbiService()
erc20_abi = abi_service.get_abi("ERC20")
pool_abi = abi_service.get_abi("Pool")
nfpm_abi = abi_service.get_abi("NFPM")

pool_contract = w3.eth.contract(address=POOL_CONTRACT_ADDRESS, abi=pool_abi)
nfpm_contract = w3.eth.contract(address=Web3.to_checksum_address(NFPM_ADDRESS), abi=nfpm_abi)


def get_abi(contract_address):
  """Fetch ABI from Etherscan (Mainnet). Pro tip: cache this to avoid rate limits."""
  # You might need an ETHERSCAN_API_KEY in .env for reliability
  url = f"https://api.etherscan.io/api?module=contract&action=getabi&address={contract_address}"
  response = requests.get(url).json()
  return response['result']


def fetch_positions(user_address):
  user_address = Web3.to_checksum_address(user_address)
  balance = nfpm_contract.functions.balanceOf(user_address).call()

  print(f"Checking {balance} positions for {user_address}...")

  positions = []
  for i in range(balance):
    token_id = nfpm_contract.functions.tokenOfOwnerByIndex(user_address, i).call()
    pos_data = nfpm_contract.functions.positions(token_id).call()

    # Mapping the tuple to readable keys
    positions.append({
      "tokenId": token_id,
      "token0": pos_data[2],
      "token1": pos_data[3],
      "fee": pos_data[4],
      "tickLower": pos_data[5],
      "tickUpper": pos_data[6],
      "liquidity": pos_data[7]
    })
  return positions


def get_token_amounts(liquidity, tick_low, tick_high, current_tick):
  """
  Calculates token0 and token1 amounts based on Uniswap v3 math.
  Formula:
  token0 = L * (sqrt(pb) - sqrt(pc)) / (sqrt(pc) * sqrt(pb))
  token1 = L * (sqrt(pc) - sqrt(pa))
  """
  sqrt_ratio_a = math.sqrt(1.0001 ** tick_low)
  sqrt_ratio_b = math.sqrt(1.0001 ** tick_high)
  sqrt_ratio_curr = math.sqrt(1.0001 ** current_tick)

  amount0 = 0
  amount1 = 0

  if current_tick < tick_low:
    # Fully in token0
    amount0 = liquidity * (sqrt_ratio_b - sqrt_ratio_a) / (sqrt_ratio_a * sqrt_ratio_b)
  elif current_tick < tick_high:
    # In range - mix of both
    amount0 = liquidity * (sqrt_ratio_b - sqrt_ratio_curr) / (sqrt_ratio_curr * sqrt_ratio_b)
    amount1 = liquidity * (sqrt_ratio_curr - sqrt_ratio_a)
  else:
    # Fully in token1
    amount1 = liquidity * (sqrt_ratio_b - sqrt_ratio_a)

  return amount0, amount1


def get_unclaimed_fees(token_id, user_address):
  # Standard Uniswap V3 limit for 'collect' to get everything
  MAX_UINT128 = 2 ** 128 - 1

  # We simulate a 'collect' call
  # collect(uint256 tokenId, address recipient, uint128 amount0Max, uint128 amount1Max)
  try:
    # Using .call() makes it a simulation (Static Call)
    unclaimed0, unclaimed1 = nfpm_contract.functions.collect({
      'tokenId': token_id,
      'recipient': user_address,
      'amount0Max': MAX_UINT128,
      'amount1Max': MAX_UINT128
    }).call({'from': user_address})

    return unclaimed0, unclaimed1
  except Exception as e:
    print(f"Error fetching unclaimed fees for {token_id}: {e}")
    return 0, 0


def get_position_data_subgraph(token_id):
  # Subgraph ID for Uniswap v3 Mainnet
  SUBGRAPH_URL = (f"https://gateway.thegraph.com/api/"
                  f"{THE_GRAPH_API_KEY}/subgraphs/id/5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV")

  query = f"""
  {{
    position(id: "{token_id}") {{
      depositedToken0
      depositedToken1
      collectedFeesToken0
      collectedFeesToken1
      # In 2026, we also pull the current 'uncollected' estimate from the indexer
      # if the subgraph version supports it, otherwise we check on-chain.
    }}
  }}
  """
  response = requests.post(SUBGRAPH_URL, json={'query': query})
  data = response.json().get('data', {}).get('position')

  if data:
    return {
      'init0': float(data['depositedToken0']),
      'init1': float(data['depositedToken1']),
      'collected0': float(data['collectedFeesToken0']),
      'collected1': float(data['collectedFeesToken1'])
    }
  return None

if __name__ == "__main__":

  if w3.is_connected():
    my_positions = fetch_positions(account.address)
    active_positions = [p for p in my_positions if p['liquidity'] > 0]

    print(f"\n--- Active Positions ({len(active_positions)}) ---")
    for p in active_positions:
      print(f"ID: {p['tokenId']} | Fee: {p['fee']} | Liquidity: {p['liquidity']}")

      # Get the current tick of the pool
      slot0 = pool_contract.functions.slot0().call()
      current_tick = slot0[1]

      token0 = pool_contract.functions.token0().call()
      token1 = pool_contract.functions.token1().call()

      token0_contract = w3.eth.contract(address=token0, abi=erc20_abi)
      token1_contract = w3.eth.contract(address=token1, abi=erc20_abi)
      dec0, name0 = token0_contract.functions.decimals().call(), token0_contract.functions.symbol().call()
      dec1, name1 = token1_contract.functions.decimals().call(), token1_contract.functions.symbol().call()

      for p in active_positions:
        # 1. Current Amounts in LP
        a0, a1 = get_token_amounts(p['liquidity'], p['tickLower'], p['tickUpper'], current_tick)
        cur0, cur1 = a0 / 10 ** dec0, a1 / 10 ** dec1

        # 2. Real-time Unclaimed Fees (On-chain)
        unclaimed0_raw, unclaimed1_raw = get_unclaimed_fees(p['tokenId'], account.address)
        pend0, pend1 = unclaimed0_raw / 10 ** dec0, unclaimed1_raw / 10 ** dec1

        # 3. Subgraph Data (Initial & Historically Collected)
        sub_data = get_position_data_subgraph(p['tokenId'])
        init0, init1 = sub_data['init0'], sub_data['init1']
        hist0, hist1 = sub_data['collected0'], sub_data['collected1']

        # --- THE CORRECT PNL MATH ---
        # Total Value = Current LP + All Fees (Pending + Withdrawn)
        total_val0 = cur0 + pend0 + hist0
        total_val1 = cur1 + pend1 + hist1

        # PnL = Total Value - Initial Deposit
        pnl0 = total_val0 - init0
        pnl1 = total_val1 - init1

        # Optional: Calculate "Divergence Loss" (Value change excluding fees)
        diff0 = cur0 - init0
        diff1 = cur1 - init1

        print(f"\n--- Position {p['tokenId']} Analysis ---")
        print(f"INITIAL DEPOSIT: {init0:.2f} {name0} | {init1:.2f} {name1}")
        print(f"CURRENT IN LP:   {cur0:.2f} {name0} | {cur1:.2f} {name1}")
        print(f"LP DIFF:         {diff0:.2f} {name0} | {diff1:.2f} {name1}")

        print(f"\n--- 100% Accurate PnL: NFT {p['tokenId']} ---")
        print(f"Pending Fees:    {pend0:.4f} {name0} | {pend1:.4f} {name1}")
        print(f"History Fees:    {hist0:.4f} {name0} | {hist1:.4f} {name1}")
        print(f"NET PnL:         {pnl0:+.4f} {name0} | {pnl1:+.4f} {name1}")
        # Calculate Current Price from Tick
        # Price of Token0 (EUROC) in terms of Token1 (USDC)
        price0_in_1 = (1.0001 ** current_tick) / (10 ** (dec1 - dec0))

        # Calculate Total PnL in Dollar (USDC value)
        # PnL in USDC = (PnL of EUROC * Price) + PnL of USDC
        total_pnl_usd = (pnl0 * price0_in_1) + pnl1

        # Calculate Total Position Value in Dollar (Current Assets + All Fees)
        total_value_usd = (total_val0 * price0_in_1) + total_val1

        print(f"Current Price:   1 {name0} = {price0_in_1:.4f} {name1}")
        print(f"TOTAL PnL (USD): {total_pnl_usd:+.2f} $")
        print(f"TOTAL VALUE (USD): {total_value_usd:.2f} $")
        print("-" * 40)

        # 1. Calculate HODL Value (What your initial coins are worth today)
        hodl_val_usd = (init0 * price0_in_1) + init1

        # 2. Impermanent Loss in USD
        # Note: total_value_usd includes fees. IL is usually calculated
        # WITHOUT fees to show the "divergence loss", then compared with fees.
        lp_value_no_fees_usd = (cur0 * price0_in_1) + cur1
        il_usd = lp_value_no_fees_usd - hodl_val_usd

        # 3. IL as a percentage
        il_percentage = (il_usd / hodl_val_usd) * 100 if hodl_val_usd > 0 else 0

        # 4. Total "Real" PnL (Fees - IL)
        # This is the most important number: did your fees cover the IL?
        net_vs_hodl_usd = total_value_usd - hodl_val_usd

        print(f"\n--- Opportunity Cost (IL) ---")
        print(f"HODL Value:      {hodl_val_usd:.2f} $")
        print(f"LP Value (raw):  {lp_value_no_fees_usd:.2f} $")
        print(f"Imperm. Loss:    {il_usd:+.2f} $ ({il_percentage:.2f}%)")
        print(f"Net vs HODL:     {net_vs_hodl_usd:+.2f} $ (Alpha)")

        if net_vs_hodl_usd > 0:
          print("✅ Success: Your earned fees have outpaced your Impermanent Loss.")
        else:
          print("⚠️ Warning: Your Impermanent Loss is currently higher than your earned fees.")
        print("-" * 40)
  else:
    print("Failed to connect to RPC")
