import os
import sys
import json
import crypto
from block import Block
from transaction import Transaction
from rules import valid_block_hash


STORAGE_DIR = os.path.join(os.path.dirname(__file__), "chain")


class BlockChain:
    def __init__(self, storage_dir=STORAGE_DIR):
        self.storage_dir = storage_dir

        self.levels = []             # level  -> { block_hash -> Block }
        self.transactions = dict()   # txn_id -> Transaction

        # load genesis block
        assert self.load_block_file(0), "Invalid Genesis Block"
    
    def load_block_file(self, level):
        block_file = os.path.join(self.storage_dir, str(level))
        
        if not os.path.exists(block_file):
            return False
        
        blocks = []

        with open(block_file, 'r') as stream:
            for line in stream.readlines():
                block_json = json.loads(line.strip())
                block = Block.from_json(block_json)
                if block is None:
                    print('invalid block')
                    continue
                blocks.append(block)
        
        if level == 0 and len(blocks) != 1:
            # incorrect number of genesis blocks
            return False
        
        for block in blocks:
            self.load_block(block)
        
        return True
    
    def load_block(self, block: Block):
        if not self.verify_block(block):
            # invalid block, reject
            return False
        
        diff = block.height - len(self.levels) + 1
        for _ in range(diff):
            self.levels.append(dict())
        
        # add block
        self.levels[block.height][block.block_hash] = block

        # add transaction
        for txn in block.transactions:
            self.transactions[txn.txn_id] = txn
        
        return True
    
    def verify_transaction(self, txn: Transaction, is_coinbase: bool):
        if txn.txn_id in self.transactions:
            # duplicate transaction
            print('duplicate transaction', file=sys.stderr)
            return False
        
        if txn.txn_id != txn.compute_txn_id():
            # invalid hash
            print('invalid hash', file=sys.stderr)
            return False
        
        sender_pubkey = None
        in_tot = 0

        if is_coinbase:
            if len(txn.inputs) != 0 or len(txn.outputs) != 1:
                # invalid coinbase
                print('invalid coinbase', file=sys.stderr)
                return False
            sender_pubkey = txn.outputs[0].pub_key

        for txn_in in txn.inputs:
            if txn_in.txn_id not in self.transactions:
                # incoming transaction doesn't exist
                print('incoming txn does not exist', file=sys.stderr)
                return False
            
            prev_txn = self.transactions[txn_in.txn_id]

            if txn_in.index < 0 or txn_in.index >= len(prev_txn.outputs):
                # invalid index
                print('invalid index', file=sys.stderr)
                return False
            
            prev_coin = prev_txn.outputs[txn_in.index]

            if sender_pubkey is None:
                sender_pubkey = prev_coin.pub_key
            elif sender_pubkey != prev_coin.pub_key:
                # all incoming txns should come from same peer
                print('all incoming not from same peer', file=sys.stderr)
                return False
            
            if prev_coin.spent:
                # coin already spent
                print('coin already spent', file=sys.stderr)
                return False

            in_tot += prev_coin.amount
        
        out_tot = 0
        for out_txn in txn.outputs:
            if out_txn.amount < 0:
                # invalid amount
                print('invalid amount', file=sys.stderr)
                return False
            
            out_tot += out_txn.amount
        
        if not is_coinbase and in_tot != out_tot:
            # invalid amounts
            print('mismatching amounts', file=sys.stderr)
            return False
        
        sender_pubkey_obj = crypto.bytes_to_public_key(sender_pubkey)
        if not txn.verify_signature(sender_pubkey_obj):
            # invalid signature
            print('invalid signature', file=sys.stderr)
            return False
        
        return True
    
    def verify_block(self, block: Block):
        h = block.compute_hash()
        if block.block_hash != h:
            # incorrect hash
            print('incorrect hash', file=sys.stderr)
            return False
        if not valid_block_hash(h):
            # invalid hash
            print('invalid hash', file=sys.stderr)
            return False
        
        if len(block.transactions) < 1:
            # needs at least 1 txn
            print('no transactions', file=sys.stderr)
            return False
        
        for i, txn in enumerate(block.transactions):
            # first txn is a coinbase txn
            is_coinbase = (i == 0)
            if not self.verify_transaction(txn, is_coinbase):
                print('unable to verify transaction', file=sys.stderr)
                return False
        
        return True



if __name__ == "__main__":
    bc = BlockChain()
    print("initialized chain with genesis block:")
    print(list(bc.levels[0].values())[0].to_json())
