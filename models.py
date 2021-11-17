from dataclass import dataclass
from typing import List


MAX_TXN_COUNT = 10


@dataclass
class Block:
    height: int
    prev_hash: bytes
    nonce: int
    transactions: List[Transaction]


@dataclass
class Transaction:
    id_: str
    is_coinbase: true
    from_: bytes
    to_: bytes
    signature: bytes
    amount: int


@dataclass
class Coin:
    pass

