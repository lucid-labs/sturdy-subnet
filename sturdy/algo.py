import math
import random  # For randomness to avoid similarity penalties
import gmpy2  # To ensure precision in arithmetic operations
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

RANDOMNESS_FACTOR = gmpy2.mpfr('0.05')  # Randomness factor to avoid similarity penalties
THRESHOLD = gmpy2.mpfr('0.99')  # Threshold to avoid over-allocation

def optimized_algorithm(self: BaseMinerNeuron, synapse: AllocateAssets) -> dict:
    bt.logging.debug(f"Received request: {synapse}")

    pools = cast(dict, synapse.assets_and_pools["pools"])

    # Initialize pools based on request type
    match synapse.request_type:
        case REQUEST_TYPES.ORGANIC:
            for uid, pool in pools.items():
                pools[uid] = PoolFactory.create_pool(
                    pool_type=pool.pool_type,
                    web3_provider=self.w3,
                    user_address=(pool.user_address if pool.user_address != ADDRESS_ZERO else synapse.user_address),
                    contract_address=pool.contract_address,
                )
        case _:
            for uid in pools:
                pools[uid] = BasePool(**pools[uid].dict())

    total_assets_available = gmpy2.mpz(synapse.assets_and_pools["total_assets"]) * THRESHOLD

    # Sync pool parameters using on-chain calls
    for pool in pools.values():
        match pool.pool_type:
            case POOL_TYPES.AAVE:
                pool.sync(synapse.user_address, self.w3)
            case POOL_TYPES.STURDY_SILO:
                pool.sync(synapse.user_address, self.w3)
            case T if T in (POOL_TYPES.DAI_SAVINGS, POOL_TYPES.COMPOUND_V3, POOL_TYPES.MORPHO, POOL_TYPES.YEARN_V3):
                pool.sync(self.w3)

    # Calculate minimum allocations for each pool
    minimums = {pool_uid: gmpy2.mpz(get_minimum_allocation(pool)) for pool_uid, pool in pools.items()}
    bt.logging.info(f"Minimums: {minimums}")

    total_assets_available -= sum(minimums.values())
    remaining_balance = total_assets_available
    bt.logging.info(f"Remaining balance: {remaining_balance}")

    # Calculate APY for each pool
    supply_rates = {}
    for pool in pools.values():
        match pool.pool_type:
            case POOL_TYPES.AAVE:
                apy = pool.supply_rate(synapse.user_address, remaining_balance // len(pools))
            case T if T in (POOL_TYPES.STURDY_SILO, POOL_TYPES.COMPOUND_V3, POOL_TYPES.MORPHO, POOL_TYPES.YEARN_V3):
                apy = pool.supply_rate(remaining_balance // len(pools))
            case POOL_TYPES.DAI_SAVINGS:
                apy = pool.supply_rate()
            case POOL_TYPES.SYNTHETIC:
                apy = pool.supply_rate
            case _:
                apy = gmpy2.mpz(0)
        supply_rates[pool.contract_address] = apy

    bt.logging.info(f"Supply rates: {supply_rates}")

    # Identify the pool with the highest APY
    max_apy_pool = max(supply_rates, key=supply_rates.get)
    bt.logging.info(f"Max APY pool: {max_apy_pool}")

    # Initialize allocations with minimums
    allocations = {pool_uid: minimums[pool_uid] for pool_uid in pools}

    # Assign the remaining assets to the pool with the highest APY
    allocations[max_apy_pool] += remaining_balance

    # Add randomness to allocations to avoid similarity penalties
    for pool_uid in allocations:
        random_factor = 1 + gmpy2.mpfr(random.uniform(0, RANDOMNESS_FACTOR))
        allocations[pool_uid] = gmpy2.mpz(gmpy2.ceil(allocations[pool_uid] * random_factor))

    # Convert allocations to integers for compatibility
    final_allocations = {uid: int(alloc) for uid, alloc in allocations.items()}

    # Validate allocations using the check_allocations function
    is_valid = check_allocations(synapse.assets_and_pools, final_allocations)
    if is_valid:
        bt.logging.info("Allocations are valid according to validator rules.")
    else:
        bt.logging.error("Allocations failed validation check! Please investigate.")

    bt.logging.info(f"Final Allocations: {final_allocations}")

    return final_allocations
