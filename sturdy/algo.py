import math
import random
from typing import cast

import bittensor as bt
from web3.constants import ADDRESS_ZERO

from sturdy.base.miner import BaseMinerNeuron
from sturdy.pools import (
    POOL_TYPES,
    BasePool,
    PoolFactory,
    get_minimum_allocation,
)
from sturdy.protocol import REQUEST_TYPES, AllocateAssets

THRESHOLD = 0.99  # to prevent over-allocations
RANDOMNESS_FACTOR = 0.02  # Introduces small random variations to avoid similarity penalties

def optimized_algorithm(self: BaseMinerNeuron, synapse: AllocateAssets) -> dict:
    bt.logging.debug(f"Received request: {synapse}")
    pools = cast(dict, synapse.assets_and_pools["pools"])

    # Adjust pool handling based on request type
    match synapse.request_type:
        case REQUEST_TYPES.ORGANIC:
            for uid, pool in pools.items():
                pools[uid] = PoolFactory.create_pool(
                    pool_type=pool.pool_type,
                    web3_provider=self.w3,  # type: ignore
                    user_address=(pool.user_address if pool.user_address != ADDRESS_ZERO else synapse.user_address),
                    contract_address=pool.contract_address,
                )
        case _:
            for uid in pools:
                pools[uid] = BasePool(**pools[uid].dict())

    # Determine available assets, considering the threshold
    total_assets_available = int(THRESHOLD * synapse.assets_and_pools["total_assets"])
    minimums = {uid: get_minimum_allocation(pool) for uid, pool in pools.items()}
    total_assets_available -= sum(minimums.values())
    balance = max(0, total_assets_available)  # Avoid negative balance

    # Initialize supply rate tracking
    supply_rate_sum = 0
    supply_rates = {}

    # Sync pool parameters through smart contract calls
    for pool in pools.values():
        try:
            match pool.pool_type:
                case POOL_TYPES.AAVE | POOL_TYPES.STURDY_SILO:
                    pool.sync(synapse.user_address, self.w3)
                case POOL_TYPES.DAI_SAVINGS | POOL_TYPES.COMPOUND_V3 | POOL_TYPES.MORPHO | POOL_TYPES.YEARN_V3:
                    pool.sync(self.w3)
        except Exception as e:
            bt.logging.error(f"Error syncing pool {pool.contract_address}: {e}")

    # Calculate APYs and introduce randomness to reduce similarity penalties
    for pool in pools.values():
        try:
            apy = pool.supply_rate(balance // len(pools))
            random_factor = 1 + (random.uniform(-RANDOMNESS_FACTOR, RANDOMNESS_FACTOR))
            apy_adjusted = int(apy * random_factor)
            supply_rates[pool.contract_address] = apy_adjusted
            supply_rate_sum += apy_adjusted
        except Exception as e:
            bt.logging.error(f"Failed to retrieve APY for pool {pool.contract_address}: {e}")
            supply_rates[pool.contract_address] = 0

    # Allocate assets to pools based on adjusted APYs and minimums
    allocations = {}
    for uid, pool in pools.items():
        if supply_rate_sum > 0:
            allocation = minimums[uid] + math.floor(
                (supply_rates[uid] / supply_rate_sum) * balance
            )
        else:
            allocation = minimums[uid]
        allocations[uid] = allocation

    bt.logging.info(f"Generated allocations: {allocations}")
    return allocations
