from random import randint
import crypto
from rules import valid_block_hash, MINING_REWARD
from utils import bytes_to_bits, get_logger
from block import Block
from transaction import Transaction, TxnInput, TxnOutput


class Strategy:
    RANDOM = 0
    INCREMENT = 1


class Miner:
    def __init__(self, pub_key, pri_key, strategy=Strategy.RANDOM):
        self.pub_key = pub_key
        self.pri_key = pri_key
        self.strategy = strategy

        self.logger = get_logger()
        self.pending_txns = []
        
        # INCREMENT strategy
        self.i = 0
    
    def add_pending_txn(self, txn: Transaction):
        self.pending_txns.append(txn)
    
    def num_pending_txns(self):
        return len(self.pending_txns)

    def reset_pending_txns(self):
        self.pending_txns = [self.generate_coinbase_txn()]

    def first_nonce(self):
        self.i = 0

    def next_nonce(self):
        nonce = None

        if self.strategy == Strategy.RANDOM:
            nonce = randint(0, 1 << 256)
        elif self.strategy == Strategy.INCREMENT:
            nonce = self.i
            self.i += 1
        
        return nonce
    
    def compose_block(self, prev_hash, height):
        return Block(prev_hash, height, 0, self.pending_txns)
    
    def valid_nonce(self, block, nonce):
        h = block.compute_hash(nonce)
        return valid_block_hash(h)
    
    def generate_coinbase_txn(self):
        txns_in = []
        txns_out = [TxnOutput(self.pub_key, MINING_REWARD)]
        txn = Transaction(txns_in, txns_out)
        txn.sign(self.pri_key)
        return txn


if __name__ == "__main__":
    from time import time
    import json

    # create a genesis block

    pub_key = crypto.load_public_key()
    pri_key = crypto.load_private_key()

    m = Miner(pub_key, pri_key)
    txn = m.generate_coinbase_txn()
    print("COINBASE TXN:", txn.to_json())
    assert txn.verify_signature(pub_key)

    b = Block(b'0', 0, 0, [txn])

    s = time()
    m.first_nonce()
    while nonce := m.next_nonce():
        if m.valid_nonce(b, nonce):
            b.set_nonce(nonce)
            break
    
    print("GENESIS BLOCK:", json.dumps(b.to_json()))
    
    bits = bytes_to_bits(b.block_hash)
    print('nonce:', nonce)
    print('hash:', ''.join(map(str, bits)))
    print('time:', time() - s)

