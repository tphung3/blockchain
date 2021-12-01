from random import randint
import crypto
from rules import valid_block_hash, MINING_REWARD
from utils import bytes_to_bits
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

        self.block = None
        self.transactions = dict()  # { txn_id -> Transaction }
        
        # INCREMENT strategy
        self.i = 0

    def add_txn(self, txn: Transaction):
        self.transactions[txn.txn_id] = txn
    
    def rem_txn(self, txn: Transaction):
        pass

    def reset_block(self):
        pass

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
            b.nonce = nonce
            break
    
    b.block_hash = b.compute_hash(nonce)
    print("GENESIS BLOCK:", json.dumps(b.to_json()))
    
    bits = bytes_to_bits(b.block_hash)
    print('nonce:', nonce)
    print('hash:', ''.join(map(str, bits)))
    print('time:', time() - s)

