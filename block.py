import json
import crypto
from typing import List
from transaction import Transaction


class Block:
    def __init__(self,
            prev_hash: bytes,                   # 256 bits
            height: int,                        # 32  bits
            nonce: int,                         # 256 bits
            transactions: List[Transaction],
            block_hash: bytes = None):          # 256 bits

        self.prev_hash = prev_hash
        self.height = height
        self.nonce = nonce
        self.transactions = transactions
        self.block_hash = block_hash

    @classmethod
    def from_json(cls, json_data):
        attrs = ("hash", "prev_hash", "height", "nonce", "transactions")
        for attr in attrs:
            if json_data.get(attr) is None:
                print("missing attr:", attr)
                return None

        txns = [Transaction.from_json(txn) for txn in json_data['transactions']]
        if not all(txns):
            print("not all:", txns)
            return None

        return Block(
            bytes.fromhex(json_data['prev_hash']),
            json_data['height'],
            json_data['nonce'],
            txns,
            bytes.fromhex(json_data['hash'])
        )

    def to_json(self):
        return {
            "hash": self.block_hash.hex(),
            "prev_hash": self.prev_hash.hex(),
            "height": self.height,
            "nonce": self.nonce,
            "transactions": [txn.to_json() for txn in self.transactions]
        }

    def compute_hash(self, nonce=None):
        if nonce is None:
            nonce = self.nonce

        data = b''
        data += self.prev_hash
        data += self.height.to_bytes(4, 'big')  # 32 bits
        data += nonce.to_bytes(32, 'big')       # 256 bits

        txns = [txn.to_json() for txn in self.transactions]
        data += json.dumps(txns).encode()

        return crypto.hash_data(data)

