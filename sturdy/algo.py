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
)
from sturdy.protocol import REQUEST_TYPES, AllocateAssets

THRESHOLD = 0.99  # Used to avoid over-allocations

# Optimized Allocation Algorithm
def naive_algorithm(self: BaseMinerNeuron, synapse: AllocateAssets) -> dict:
    bt.logging.debug(f"Received request type: {synapse.request_type}")

    # Extract pools from the synapse request
    pools = cast(dict, synapse.assets_and_pools["pools"])

    # Initialize pools based on their types
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
        case _:  # Assuming synthetic request
            for uid in pools:
                pools[uid] = BasePool(**pools[uid].dict())

    # Calculate available assets
    total_assets_available = int(THRESHOLD * synapse.assets_and_pools["total_assets"])

    # Sync pool parameters and fetch supply rates
    supply_rates = {}
    for pool in pools.values():
        match pool.pool_type:
            case POOL_TYPES.AAVE:
                pool.sync(synapse.user_address, self.w3)
            case POOL_TYPES.STURDY_SILO:
                pool.sync(synapse.user_address, self.w3)
            case T if T in (POOL_TYPES.DAI_SAVINGS, POOL_TYPES.COMPOUND_V3):
                pool.sync(self.w3)

    # Calculate minimum allocation per pool
    minimums = {}
    for pool_uid, pool in pools.items():
        match pool.pool_type:
            case POOL_TYPES.AAVE:
                minimums[pool_uid] = pool._nextTotalStableDebt + pool._totalVariableDebt
            case POOL_TYPES.STURDY_SILO:
                minimums[pool_uid] = pool._totalBorrow.amount
            case POOL_TYPES.COMPOUND_V3:
                minimums[pool_uid] = pool._total_borrow
            case POOL_TYPES.SYNTHETIC:
                minimums[pool_uid] = pool.borrow_amount
            case _:
                minimums[pool_uid] = total_assets_available // len(pools)

    # Calculate the remaining balance after allocating minimums
    total_assets_available -= sum(minimums.values())
    balance = int(total_assets_available)

    # Fetch APY for each pool and identify the pool with the highest APY
    best_pool_uid = None
    max_apy = -1
    for pool_uid, pool in pools.items():
        apy = 0
        match pool.pool_type:
            case POOL_TYPES.AAVE:
                apy = pool.supply_rate(synapse.user_address, balance // len(pools))
            case T if T in (POOL_TYPES.STURDY_SILO, POOL_TYPES.COMPOUND_V3):
                apy = pool.supply_rate(balance // len(pools))
            case POOL_TYPES.DAI_SAVINGS:
                apy = pool.supply_rate()
            case POOL_TYPES.SYNTHETIC:
                apy = pool.supply_rate

        supply_rates[pool_uid] = apy

        # Track the pool with the highest APY
        if apy > max_apy:
            max_apy = apy
            best_pool_uid = pool_uid

    # Allocate the remaining balance to the pool with the highest APY
    final_allocations = {pool_uid: minimums[pool_uid] for pool_uid in pools}
    if best_pool_uid:
        final_allocations[best_pool_uid] += balance

    bt.logging.info(f"Final Allocations: {final_allocations}")
    return final_allocations
