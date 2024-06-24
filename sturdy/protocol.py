# The MIT License (MIT)
# Copyright © 2023 Yuma Rao
# Copyright © 2023 Syeam Bin Abdullah

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
# documentation files (the “Software”), to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial portions of
# the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
# THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
# DEALINGS IN THE SOFTWARE.

from typing import Dict, Optional, Union
from typing_extensions import TypedDict
import bittensor as bt
from pydantic import BaseModel, Field

from sturdy.pools import POOL_TYPES, BasePoolModel, ChainBasedPoolModel


class AllocInfo(TypedDict):
    apy: str
    allocations: Union[Dict[str, float], None]


class AllocateAssetsRequest(BaseModel):
    class Config:
        use_enum_values = True

    type: POOL_TYPES = Field(
        default=POOL_TYPES.DEFAULT, required=True, description="type of pool"
    )
    assets_and_pools: Dict[
        str, Union[Dict[str, Union[BasePoolModel, ChainBasedPoolModel]], float]
    ] = Field(
        ...,
        required=True,
        description="pools for miners to produce allocation amounts for - uid -> pool_info",
    )


class AllocateAssetsResponse(BaseModel):
    class Config:
        use_enum_values = True

    allocations: Dict[str, AllocInfo] = Field(
        ...,
        required=True,
        description="allocations produce by miners",
    )


class AllocateAssetsBase(BaseModel):
    """
    This protocol helps in handling the distribution of validator-generated pools from
    the validator to miners, and then gathering miner-generated allocations afterwards.

    Attributes:
    - pools: A list of pools sent by the validator.
    - allocations: A list of pools and their respective allocations, when filled, represents the response from the miner.
    """

    class Config:
        use_enum_values = True

    # Required request input, filled by sending dendrite caller.
    type: POOL_TYPES = Field(
        default=POOL_TYPES.DEFAULT, required=True, description="type of pool"
    )
    assets_and_pools: Dict[
        str, Union[Dict[str, Union[BasePoolModel, ChainBasedPoolModel]], float]
    ] = Field(
        ...,
        required=True,
        description="pools for miners to produce allocation amounts for - uid -> pool_info",
    )

    # Optional request output, filled by recieving axon.
    allocations: Optional[Dict[str, float]] = Field(
        None,
        description="allocations produce by miners",
    )


class AllocateAssets(bt.Synapse, AllocateAssetsBase):
    def __str__(self):
        # TODO: figure out how to only show certain keys from pools and/or allocations
        return (
            f"AllocateAssets(type={self.type}, assets_and_pools={self.assets_and_pools})"
            f"allocations={self.allocations}"
        )
