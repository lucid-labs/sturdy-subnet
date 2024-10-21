import math
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
)
from sturdy.protocol import REQUEST_TYPES, AllocateAssets

THRESHOLD = 0.99  # Used to avoid over-allocations

def naive_algorithm(self: BaseMinerNeuron, synapse: AllocateAssets) -> dict:
    bt.logging.debug(f"received request type: {synapse.request_type}")
    
    pools = cast(dict, synapse.assets_and_pools["pools"])
    
    # Step 1: Initialize pools based on request type
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
        case _:  # Handle synthetic requests
            for uid in pools:
                pools[uid] = BasePool(**pools[uid].dict())

    # Step 2: Calculate total available assets after minimum allocations
    total_assets_available = int(THRESHOLD * synapse.assets_and_pools["total_assets"])
    minimums = {pool_uid: get_minimum_allocation(pool) for pool_uid, pool in pools.items()}
    total_assets_available -= sum(minimums.values())

    # Step 3: Calculate APYs for each pool
    supply_rates = {}
    max_apy_pool_uid = None
    max_apy = -1

    for pool_uid, pool in pools.items():
        # Sync pool data from the chain
        match pool.pool_type:
            case POOL_TYPES.AAVE:
                pool.sync(synapse.user_address, self.w3)
            case POOL_TYPES.STURDY_SILO:
                pool.sync(synapse.user_address, self.w3)
            case T if T in (POOL_TYPES.DAI_SAVINGS, POOL_TYPES.COMPOUND_V3):
                pool.sync(self.w3)
            case _:
                pass

        # Calculate the APY for the current pool
        apy = pool.supply_rate(
            amount=total_assets_available // len(pools)
        )  # Adjust the amount as needed

        supply_rates[pool_uid] = apy

        # Track the pool with the highest APY
        if apy > max_apy:
            max_apy = apy
            max_apy_pool_uid = pool_uid

    # Step 4: Allocate assets
    allocations = {pool_uid: minimums[pool_uid] for pool_uid in pools}

    # Allocate all remaining assets to the pool with the highest APY
    if max_apy_pool_uid:
        allocations[max_apy_pool_uid] += total_assets_available

    bt.logging.info(f"Allocations: {allocations}")
    return allocations
