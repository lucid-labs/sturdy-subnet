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
            for uid, pool in pools:
                pools[uid] = PoolFactory.create_pool(
                    pool_type=pool.pool_type,
                    web3_provider=self.w3,  # type: ignore[]
                    user_address=(
                        pool.user_address if pool.user_address != ADDRESS_ZERO else synapse.user_address
                    ),  # TODO: is there a cleaner way to do this?
                    contract_address=pool.contract_address,
                )

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

    # check the amounts that have been borrowed from the pools - and account for them
    minimums = {}
    for pool_uid, pool in pools.items():
        minimums[pool_uid] = get_minimum_allocation(pool)

    total_assets_available -= sum(minimums.values())
    balance = int(total_assets_available)  # obtain supply rates of pools - aave pool and sturdy silo
    # rates are determined by making on chain calls to smart contracts
    for pool in pools.values():
        match pool.pool_type:
            case POOL_TYPES.AAVE:
                apy = pool.supply_rate(synapse.user_address, balance // len(pools))  # type: ignore[]
                supply_rates[pool.contract_address] = apy
                supply_rate_sum += apy
            case T if T in (POOL_TYPES.STURDY_SILO, POOL_TYPES.COMPOUND_V3, POOL_TYPES.MORPHO, POOL_TYPES.YEARN_V3):
                apy = pool.supply_rate(balance // len(pools))  # type: ignore[]
                supply_rates[pool.contract_address] = apy
                supply_rate_sum += apy
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
