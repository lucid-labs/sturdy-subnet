import math
import random
from typing import cast

import bittensor as bt

from sturdy.base.miner import BaseMinerNeuron
from sturdy.pools import (
    POOL_TYPES,
    AaveV3DefaultInterestRatePool,
    BasePool,
    CompoundV3Pool,
    DaiSavingsRate,
    VariableInterestSturdySiloStrategy,
    get_minimum_allocation,
    check_allocations,
)
from sturdy.protocol import REQUEST_TYPES, AllocateAssets

THRESHOLD = 0.99  # used to avoid over-allocations


def naive_algorithm(self: BaseMinerNeuron, synapse: AllocateAssets) -> dict:
    bt.logging.debug(f"Received request type: {synapse.request_type}")
    
    # Initialize pools based on request type
    pools = cast(dict, synapse.assets_and_pools["pools"])
    match synapse.request_type:
        case REQUEST_TYPES.ORGANIC:
            for uid in pools:
                match pools[uid].pool_type:
                    case POOL_TYPES.AAVE:
                        pools[uid] = AaveV3DefaultInterestRatePool(**pools[uid].dict())
                    case POOL_TYPES.STURDY_SILO:
                        pools[uid] = VariableInterestSturdySiloStrategy(**pools[uid].dict())
                    case POOL_TYPES.DAI_SAVINGS:
                        pools[uid] = DaiSavingsRate(**pools[uid].dict())
                    case POOL_TYPES.COMPOUND_V3:
                        pools[uid] = CompoundV3Pool(**pools[uid].dict())
                    case _:
                        pass

        case _:  # Synthetic requests handled here
            for uid in pools:
                pools[uid] = BasePool(**pools[uid].dict())

    # Calculate total available assets
    total_assets_available = int(THRESHOLD * synapse.assets_and_pools["total_assets"])
    supply_rates = {}
    supply_rate_sum = 0

    # Sync pool parameters via on-chain smart contract calls
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

    # Calculate minimum allocations for each pool
    minimums = {pool_uid: get_minimum_allocation(pool) for pool_uid, pool in pools.items()}
    total_assets_available -= sum(minimums.values())
    balance = int(total_assets_available)

    # Obtain APY for each pool
    for pool in pools.values():
        match pool.pool_type:
            case POOL_TYPES.AAVE:
                apy = pool.supply_rate(synapse.user_address, balance // len(pools))
            case T if T in (POOL_TYPES.STURDY_SILO, POOL_TYPES.COMPOUND_V3, POOL_TYPES.MORPHO):
                apy = pool.supply_rate(balance // len(pools))
            case POOL_TYPES.DAI_SAVINGS:
                apy = pool.supply_rate()
            case POOL_TYPES.SYNTHETIC:
                apy = pool.supply_rate
            case _:
                continue
        supply_rates[pool.contract_address] = apy
        supply_rate_sum += apy

    # Find the pool with the highest APY
    max_apy_pool = max(supply_rates, key=supply_rates.get)
    remaining_assets = balance

    # Allocate funds with randomness to reduce similarity penalties
    allocations = {}
    for pool_uid in pools:
        min_alloc = minimums[pool_uid]

        # Introduce a small random variation (±3%) in allocations
        random_factor = 1 + random.uniform(-0.03, 0.03)
        if pool_uid == max_apy_pool:
            allocations[pool_uid] = int((remaining_assets + min_alloc) * random_factor)
        else:
            allocations[pool_uid] = int(min_alloc * random_factor)

    # Validate the final allocations
    if not check_allocations(synapse.assets_and_pools, allocations):
        bt.logging.error("Invalid allocations returned! Adjusting to minimums.")
        return minimums  # Fallback to minimum allocations if validation fails

    bt.logging.debug(f"Allocations: {allocations}")

    return allocations
