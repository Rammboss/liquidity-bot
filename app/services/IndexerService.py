import os
from time import sleep

from dotenv import load_dotenv
from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3._utils.events import get_event_data

from database.database import Database
from database.models import Position
from database.repositories import (CollectEventsRepository, IndexedBlockRepository, MintEventsRepository,
                                   PositionRepository)
from logger import get_logger
from blockchain.uniswap.NoneFungibleTokenManager import NoneFungibleTokenManager
from blockchain.uniswap.Pool import Pool

load_dotenv()


class IndexerService:
  def __init__(self, db: Database):
    self._running = None
    self.logger = get_logger()
    self.db = db
    self.account: LocalAccount = Account.from_key(os.getenv("PRIVATE_KEY"))
    self.w3 = Web3(Web3.HTTPProvider(os.getenv("RPC_URL")))
    if not self.w3.is_connected():
      self.logger.error("Failed to connect to Ethereum node. Check your RPC_URL.")
      raise ConnectionError("Failed to connect to Ethereum node.")
    if not self.is_fully_synced():
      self.logger.warning("Ethereum node is still syncing. Indexer will start once syncing is complete.")
      raise ValueError("Ethereum node is still syncing.")
    self.nftm = NoneFungibleTokenManager("0xC36442b4a4522E871399CD717aBDD847Ab11FE88")
    self.event_signature_increase_liquidity = "IncreaseLiquidity(uint256,uint128,uint256,uint256)"
    self.pool = Pool("0x95DBB3C7546F22BCE375900AbFdd64a4E5bD73d6")
    self.transfer_abi = {
      "anonymous": False,
      "inputs": [
        {"indexed": True, "name": "from", "type": "address"},
        {"indexed": True, "name": "to", "type": "address"},
        {"indexed": True, "name": "tokenId", "type": "uint256"},
      ],
      "name": "Transfer",
      "type": "event"
    }
    self.blocks_per_call = 2000

    self.block_repo: IndexedBlockRepository = None
    self.mint_repo: MintEventsRepository = None
    self.collect_repo: CollectEventsRepository = None
    self.position_repo: PositionRepository = None

  def is_fully_synced(self):
    sync_status = self.w3.eth.syncing

    # If False, definitely synced
    if sync_status is False:
      return True

    # If it's your data structure, check if current matches highest
    if sync_status:
      current = sync_status['currentBlock']
      highest = sync_status['highestBlock']

      # Allow for 1-2 block difference (network lag)
      if highest - current <= 2:
        return True
      else:
        return False

    return False

  def run(self):
    self._running = True

    while self._running:
      with self.db.session() as session:
        self.block_repo = IndexedBlockRepository(session)
        self.mint_repo = MintEventsRepository(session)
        self.collect_repo = CollectEventsRepository(session)
        self.position_repo = PositionRepository(session)

        starting_block = self.block_repo.get_latest()
        latest_block = self.w3.eth.block_number

        if starting_block.latest_block == 0:
          starting_block.latest_block = 24454082

        to_block = starting_block.latest_block + self.blocks_per_call
        if to_block > latest_block:
          to_block = latest_block
          starting_block.synced = True
          self.block_repo.set_latest(starting_block.latest_block)
          self.logger.debug("Indexing complete")
          sleep(10)

        self.logger.info(f"Indexing blocks {starting_block.latest_block} - {to_block}...")

        self.find_increase_liquidity_events(starting_block.latest_block, to_block)
        self.find_decrease_liquidity_events(starting_block.latest_block, to_block)
        self.find_collect_events(starting_block.latest_block, to_block)

        self.block_repo.set_latest(to_block)

  def decode_increase_liquidity_event(self, log):
    """Decodes a Mint event log."""
    event_abi = self.nftm.contract.events.IncreaseLiquidity()._get_event_abi()
    decoded = get_event_data(self.w3.codec, event_abi, log)
    liquidity = decoded.args.liquidity
    amount0 = decoded.args.amount0
    amount1 = decoded.args.amount1
    token_id = decoded.args.tokenId

    return {
      "liquidity": liquidity,
      "amount0": amount0,
      "amount1": amount1,
      "tokenId": token_id
    }

  def get_increase_liquidity_events(self, from_block, to_block):
    """Fetches Mint events from the pool contract."""

    return self.w3.eth.get_logs({
      "fromBlock": from_block,
      "toBlock": to_block,
      "address": self.nftm.contract.address,
      "topics": ["0x" + Web3.keccak(text=self.event_signature_increase_liquidity).hex(), None]
    })

  def find_increase_liquidity_events(self, from_block: int, to_block: int):
    logs = self.get_increase_liquidity_events(from_block, to_block)
    for log in logs:
      tx_hash = log["transactionHash"].hex()
      tx = self.w3.eth.get_transaction(log["transactionHash"])

      if tx["from"].lower() == self.account.address.lower():
        decoded = self.decode_increase_liquidity_event(log)
        pos_data = self.nftm.get_position(decoded['tokenId'])
        pos = self.position_repo.get_active_by_token_id(decoded['tokenId'])

        if pos is not None:
          self.logger.info(f"Found increase liquidity event for token ID {decoded['tokenId']}.")
          self.logger.info(
            f"Current position: {self.pool.token0.format(pos.deposited_amount0)} and "
            f"{self.pool.token1.format(pos.deposited_amount1)}")
          pos.deposited_amount0 += decoded["amount0"]
          pos.deposited_amount1 += decoded["amount1"]
          self.logger.info(
            f"Updated position: {self.pool.token0.format(pos.deposited_amount0)} and "
            f"{self.pool.token1.format(pos.deposited_amount1)}")
          self.position_repo.save(pos)
        else:

          self.logger.info(
            f"Create new position with ID[{decoded['tokenId']}] {self.pool.token0.format(decoded["amount0"])} and "
            f"{self.pool.token1.format(decoded["amount1"])}")

          # 1. Fetch the pool state at the specific block of this transaction
          # tx_hash is assumed to be available in your context
          tx_receipt = self.w3.eth.get_transaction_receipt(tx_hash)
          block_number = tx_receipt['blockNumber']

          # 2. Get slot0 which contains the sqrtPriceX96 at that block
          # This represents the 'p_initial' for your IL calculation
          pool_data_at_mint = self.pool.pool_contract.functions.slot0().call(block_identifier=block_number)
          sqrt_price_x96 = pool_data_at_mint[0]

          # 3. Convert sqrtPriceX96 to a human-readable price (p_initial)
          # Adjust decimals based on your token0 and token1 (e.g., 6 for USDC/EUROC)
          dec0 = self.pool.token0.decimals
          dec1 = self.pool.token1.decimals
          p_initial = ((sqrt_price_x96 / (2 ** 96)) ** 2) * (10 ** (dec0 - dec1))

          self.logger.info(f"Position Mint Price (p_initial): {p_initial}")

          self.mint_repo.save_event(
            tx_hash,
            decoded['tokenId'],
            decoded["liquidity"],
            decoded["amount0"],
            decoded["amount1"],
            pos_data[5],
            pos_data[6]
          )

          self.position_repo.save(
            Position(
              token_id=decoded['tokenId'],
              deposited_amount0=decoded['amount0'],
              deposited_amount1=decoded['amount1'],
              current_amount0=decoded['amount0'],
              current_amount1=decoded['amount1'],
              liquidity=decoded['liquidity'],
              tick_lower=pos_data[5],
              tick_upper=pos_data[6],
              is_active=True,

            )
          )

  def get_collect_events(self, from_block, to_block):
    nfpm_address = self.nftm.contract.address
    # Correct signature for NFPM Collect event
    event_signature = "Collect(uint256,address,uint256,uint256)"
    topic0 = self.w3.keccak(text=event_signature).hex()

    all_logs = self.w3.eth.get_logs({
      "fromBlock": from_block,
      "toBlock": to_block,
      "address": nfpm_address,
      "topics": ["0x" + topic0]
    })

    my_events = []

    for log in all_logs:
      decoded_log = self.nftm.contract.events.Collect()._get_event_abi()
      decoded = get_event_data(self.w3.codec, decoded_log, log)
      if decoded.args.recipient == self.account.address:
        my_events.append(log)

    return my_events

  def find_collect_events(self, indexing_block: int, to_block: int):
    """Finds and processes Collect events for your wallet in a given block."""
    for log in self.get_collect_events(indexing_block, to_block):
      tx_hash = log["transactionHash"].hex()
      tx = self.w3.eth.get_transaction(log["transactionHash"])

      # Only consider transactions from your wallet
      if tx["from"].lower() != self.account.address.lower():
        continue

      # Decode the Collect event
      event_abi = self.nftm.contract.events.Collect()._get_event_abi()
      decoded = get_event_data(self.w3.codec, event_abi, log)

      token_id = decoded.args.tokenId
      amount0 = decoded.args.amount0
      amount1 = decoded.args.amount1

      self.logger.info(f"Collect fees event in tx {tx_hash}")
      self.logger.info(
        f"Collected fees for Position ID[{token_id}]: {self.pool.token0.format(amount0)} and "
        f"{self.pool.token1.format(amount1)}")

      position = self.position_repo.get_by_token_id(token_id)

      self.collect_repo.save(
        tx_hash,
        token_id,
        amount0,
        amount1,
        position_id=position.id
      )

  def find_decrease_liquidity_events(self, starting_block, to_block):
    """Finds and processes DecreaseLiquidity events for your wallet in a given block."""
    event_signature = "DecreaseLiquidity(uint256,uint128,uint256,uint256)"
    logs = self.w3.eth.get_logs({
      "fromBlock": starting_block,
      "toBlock": to_block,
      "address": self.nftm.contract.address,
      "topics": ["0x" + Web3.keccak(text=event_signature).hex(), None]
    })

    for log in logs:
      tx = self.w3.eth.get_transaction(log["transactionHash"])

      if tx["from"].lower() == self.account.address.lower():
        decoded = self.decode_decrease_liquidity_event(log)
        pos = self.position_repo.get_by_token_id(decoded["tokenId"])
        pos.liquidity -= decoded["liquidity"]
        if pos.liquidity <= 0:
          pos.is_active = False
        self.position_repo.save(pos)

        self.logger.info(
          f"Position ID[{decoded['tokenId']}] decreased liquidity by {self.pool.token0.format(decoded['amount0'])} and "
          f"{self.pool.token1.format(decoded['amount1'])} active: {pos.is_active}")

  def decode_decrease_liquidity_event(self, log):
    """Decodes a DecreaseLiquidity event log."""
    event_abi = self.nftm.contract.events.DecreaseLiquidity()._get_event_abi()
    decoded = get_event_data(self.w3.codec, event_abi, log)
    liquidity = decoded.args.liquidity
    amount0 = decoded.args.amount0
    amount1 = decoded.args.amount1
    token_id = decoded.args.tokenId

    return {
      "liquidity": liquidity,
      "amount0": amount0,
      "amount1": amount1,
      "tokenId": token_id
    }
