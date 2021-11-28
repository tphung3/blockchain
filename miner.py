from random import randint
import crypto
from rules import valid_block_hash, MINING_REWARD
from utils import bytes_to_bits
from block import Block
from transaction import Transaction, TxnInput, TxnOutput


class Strategy:
    RANDOM = 0
    INCREMENT = 1


def find_nonce(block, strategy=Strategy.RANDOM):
    i = 0

    while True:
        if strategy == Strategy.RANDOM:
            nonce = randint(0, 1 << 256)
        elif strategy == Strategy.INCREMENT:
            nonce = i
            i += 1
        else:
            raise ValueError("invalid strategy")

        h = block.compute_hash(nonce)

        if valid_block_hash(h):
            return nonce


def generate_coinbase_txn(public_key, private_key):
    txns_in = []
    txns_out = [TxnOutput(crypto.key_to_bytes(public_key), MINING_REWARD)]
    txn = Transaction(txns_in, txns_out)
    txn.sign(private_key)
    return txn


if __name__ == "__main__":
    from time import time
    import json

    # create a genesis block

    pub_key = crypto.load_public_key()
    pri_key = crypto.load_private_key()
    txn = generate_coinbase_txn(pub_key, pri_key)
    print("COINBASE TXN:", txn.to_json())
    assert txn.verify_signature(pub_key)

    b = Block(b'0', 0, 0, [txn])

    s = time()

    nonce = find_nonce(b, strategy=Strategy.RANDOM)
    b.nonce = nonce
    b.block_hash = b.compute_hash(nonce)
    print("GENESIS BLOCK:", json.dumps(b.to_json()))
    
    bits = bytes_to_bits(b.block_hash)
    print('nonce:', nonce)
    print('hash:', ''.join(map(str, bits)))
    print('time:', time() - s)

