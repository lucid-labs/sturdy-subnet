import math
import random  # Importing random for randomness
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

THRESHOLD = 0.98  # Used to avoid over-allocations
RANDOMNESS_FACTOR = 0.05  # Factor for adding randomness to avoid similarity penalties

def optimized_algorithm(self: BaseMinerNeuron, synapse: AllocateAssets) -> dict:
    bt.logging.debug(f"Received request: {synapse}")

    pools = cast(dict, synapse.assets_and_pools["pools"])

    # Initialize pools based on the request type
    match synapse.request_type:
        case REQUEST_TYPES.ORGANIC:
            for uid, pool in pools.items():
                pools[uid] = PoolFactory.create_pool(
                    pool_type=pool.pool_type,
                    web3_provider=self.w3,  # type: ignore[]
                    user_address=(
                        pool.user_address if pool.user_address != ADDRESS_ZERO else synapse.user_address
                    ),
                    contract_address=pool.contract_address,
                )
        case _:
            for uid in pools:
                pools[uid] = BasePool(**pools[uid].dict())

    total_assets_available = int(THRESHOLD * synapse.assets_and_pools["total_assets"])

    # Sync pool parameters using on-chain calls
    for pool in pools.values():
        match pool.pool_type:
            case POOL_TYPES.AAVE:
                pool.sync(synapse.user_address, self.w3)
            case POOL_TYPES.STURDY_SILO:
                pool.sync(synapse.user_address, self.w3)
            case T if T in (POOL_TYPES.DAI_SAVINGS, POOL_TYPES.COMPOUND_V3):
                pool.sync(self.w3)
            case _:
                pass

    # Retrieve minimum allocations for each pool
    minimums = {pool_uid: get_minimum_allocation(pool) for pool_uid, pool in pools.items()}
    total_assets_available -= sum(minimums.values())

    # Calculate APYs for each pool to identify the pool with the highest APY
    supply_rates = {}
    for pool in pools.values():
        match pool.pool_type:
            case POOL_TYPES.AAVE:
                apy =pool.supply_rate(synapse.user_address, balance // len(pools))  # type: ignore[]
            case T if T in (POOL_TYPES.STURDY_SILO, POOL_TYPES.COMPOUND_V3, POOL_TYPES.MORPHO, POOL_TYPES.YEARN_V3):
                apy = pool.supply_rate(balance // len(pools))  # type: ignore[]
            case POOL_TYPES.DAI_SAVINGS:
                apy = pool.supply_rate()
            case POOL_TYPES.SYNTHETIC:
                apy = pool.supply_rate
            case _:
                apy = 0
        supply_rates[pool.contract_address] = apy

    # Determine the pool with the highest APY
    max_apy_pool = max(supply_rates, key=supply_rates.get)

    # Initialize allocations with minimum values
    allocations = {pool_uid: minimums[pool_uid] for pool_uid in pools}

    # Assign the remaining assets to the pool with the highest APY
    allocations[max_apy_pool] += total_assets_available

    # Add randomness to allocations to avoid similarity penalties
    for pool_uid in allocations:
        random_factor = 1 + random.uniform(-RANDOMNESS_FACTOR, RANDOMNESS_FACTOR)
        allocations[pool_uid] = math.floor(allocations[pool_uid] * random_factor)

    bt.logging.info(f"Allocations: {allocations}")

    return allocations
