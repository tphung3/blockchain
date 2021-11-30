import os
import sys
import json
from dataclasses import dataclass
from typing import List
import crypto
import rules
from block import Block
from transaction import Transaction


STORAGE_DIR = os.path.join(os.path.dirname(__file__), "chain")


@dataclass
class BlockChainNode:
    prev: 'BlockChainNode'
    data: Block


class BlockChain:
    def __init__(self, storage_dir=STORAGE_DIR):
        self.storage_dir = storage_dir

        self.levels = []             # level  -> { block_hash -> BlockChainNode }
        self.transactions = dict()   # txn_id -> Transaction

        self.max_height = 0

        # load genesis block
        genesis_level = self.load_block_file(0)
        if not genesis_level:
            print("Invalid/Missing Genesis Block", file=sys.stderr)

        self.head_block = genesis_level[0]
        if not self.insert_block(self.head_block):
            print("Invalid Genesis Block", file=sys.stderr)
    
    def load_block_file(self, level: int) -> List[Block]:
        """
        Returns a list of blocks from the file at the specified level
        """
        block_file = os.path.join(self.storage_dir, str(level))
        
        if not os.path.exists(block_file):
            return None
        
        blocks = []

        with open(block_file, 'r') as stream:
            for i, line in enumerate(stream.readlines()):
                block_json = json.loads(line.strip())
                block = Block.from_json(block_json)
                if block is None:
                    print(f'invalid block on line {i} of {block_file}', file=sys.stderr)
                    continue
                blocks.append(block)
        
        if level == 0 and len(blocks) != 1:
            # incorrect number of genesis blocks
            print(f'{block_file} has the incorrect number of blocks for a genesis block', file=sys.stderr)
            return None
        
        return blocks

    def save_block_to_file(self, block: Block) -> BlockChainNode:
        block_file = os.path.join(self.storage_dir, str(block.level))

        with open(block_file, 'a') as stream:
            block_str = json.dumps(Block.to_json(block)) + "\n"
            print(block_str, file=stream)

    def previous_block_node(self, block: Block) -> BlockChainNode:
        """
        Returns the previous block chain node, which block.prev_hash references (None if no such hash exists)
        """
        return None if block.height <= 0 else self.levels[block.height - 1].get(block.prev_hash)

    def insert_block(self, block: Block) -> bool:
        """
        Insert a new block into the chain

        returns:
            True    Successful Insert
            False   Invalid block
            None    Missing previous blocks
        """
        prev = self.previous_block_node(block)

        if block.height > 0 and prev is None:
            return None

        return self.insert_block_node(BlockChainNode(prev, block))

    def insert_block_node(self, block_node: BlockChainNode) -> bool:
        """
        Insert a new block into the chain

        returns:
            True    Successful Insert
            False   Invalid block
        
        notes:
           - auto reject blocks that are >=10 blocks below tip
        """
        if block_node.data.height <= (self.max_height - rules.MAX_BLOCKS_BEHIND):
            # too far below tip to consider
            return False

        if not self.verify_block(block_node.data):
            # invalid block, reject
            return False

        # load additional levels if necessary
        diff = block_node.data.height - len(self.levels) + 1
        for _ in range(diff):
            self.levels.append(dict())
        
        if block_node.prev:
            self.move_head(self.head_block, block_node.prev)

        # apply block transactions
        self.apply_block(block_node)

        if block_node.data.height < self.max_height:
            # move head back to head_block
            self.move_head(block_node, self.head_block)
        else:
            # keep head at new block
            self.max_height = block_node.data.height
            self.head_block = block_node

        # add block
        self.levels[block_node.data.height][block_node.data.block_hash] = block_node

        return True

    def apply_block(self, block_node: BlockChainNode) -> None:
        """
        Apply block transactions onto chain, updating transaction dict accordingly
        """
        for txn in block_node.data.transactions:
            # add transaction to dict
            self.transactions[txn.txn_id] = txn

            for coin in self.coin_inputs(txn):
                coin.spent = True

    def revert_block(self, block_node: BlockChainNode) -> None:
        """
        Undo a block

        Assumptions:
            - all txns in `block_node` have been applied
        """
        for txn in reversed(block_node.data.transactions):
            # remove from dict
            self.transactions.pop(txn.txn_id)

            for coin in self.coin_inputs(txn):
                coin.spent = False

    def move_head(self, src: BlockChainNode, dst: BlockChainNode) -> BlockChainNode:
        """
        Moves head of chain from one node to another
        """
        to_apply = []

        # revert back to LCA
        while src.height > dst.height:
            self.revert_block(src.data)
            src = src.prev
        while dst.height > src.height:
            to_apply.append(dst.data)
            dst = dst.prev

        while src.data.block_hash != dst.data.block_hash and src and dst:
            self.revert_block(src.data)
            to_apply.append(dst.data)
            src = src.prev
            dst = dst.prev

        # all blocks should at least meet at genesis
        assert src.data.block_hash == dst.data.block_hash

        # move up to target
        for block in reversed(to_apply):
            self.apply_block(block)

    def verify_block(self, block: Block) -> bool:
        if block.height < 0:
            print('invalid block height', file=sys.stderr)
            return False
        elif block.height == 0 and len(self.levels) >= 1:
            print("can't overwrite genesis block", file=sys.stderr)
            return False
        
        h = block.compute_hash()

        if block.block_hash != h:
            print('incorrect hash', file=sys.stderr)
            return False

        if not rules.valid_block_hash(h):
            print('invalid hash', file=sys.stderr)
            return False

        if len(block.transactions) < 1:
            print('no transactions', file=sys.stderr)
            return False

        block_txns = set()
        for i, txn in enumerate(block.transactions):
            if txn.txn_id in block_txns:
                return False
            block_txns.add(txn.txn_id)

            # first txn is a coinbase txn
            is_coinbase = (i == 0)

            if not self.verify_transaction(txn, is_coinbase):
                print('unable to verify transaction', file=sys.stderr)
                return False

        return True

    def verify_transaction(self, txn: Transaction, is_coinbase: bool) -> bool:
        if txn.txn_id in self.transactions:
            print('duplicate transaction', file=sys.stderr)
            return False
        
        if txn.txn_id != txn.compute_txn_id():
            print('invalid hash', file=sys.stderr)
            return False
        
        sender_pubkey = None
        in_tot = 0

        if is_coinbase:
            if len(txn.inputs) != 0 or len(txn.outputs) != 1:
                print('invalid coinbase', file=sys.stderr)
                return False
            sender_pubkey = txn.outputs[0].pub_key

        for txn_in in txn.inputs:
            if txn_in.txn_id not in self.transactions:
                print('incoming txn does not exist', file=sys.stderr)
                return False
            
            prev_txn = self.transactions[txn_in.txn_id]

            if txn_in.index < 0 or txn_in.index >= len(prev_txn.outputs):
                print('invalid index', file=sys.stderr)
                return False
            
            prev_coin = prev_txn.outputs[txn_in.index]

            if sender_pubkey is None:
                sender_pubkey = prev_coin.pub_key
            elif sender_pubkey != prev_coin.pub_key:
                print('all incoming not from same peer', file=sys.stderr)
                return False
            
            if prev_coin.spent:
                print('coin already spent', file=sys.stderr)
                return False

            in_tot += prev_coin.amount
        
        out_tot = 0
        for out_txn in txn.outputs:
            if out_txn.amount < 0:
                print('invalid amount', file=sys.stderr)
                return False
            
            out_tot += out_txn.amount
        
        if not is_coinbase and in_tot != out_tot:
            print('mismatching amounts', file=sys.stderr)
            return False
        
        if not txn.verify_signature(sender_pubkey):
            print('invalid signature', file=sys.stderr)
            return False
        
        return True

    def coin_inputs(self, txn: Transaction):
        coins = []
        for txn_in in txn.inputs:
            if txn_in.txn_id not in self.transactions:
                continue
            coins.append(self.transactions[txn_in.txn_id].outputs[txn_in.index])
        return coins


if __name__ == "__main__":
    bc = BlockChain()
    print("initialized chain with genesis block:")
    print(json.dumps(bc.head_block.data.to_json(), indent=2))
    print("Transactions:")
    for txn_id, txn in bc.transactions.items():
        print("TXN ID:", txn_id.hex())
        for prev_txn_out in bc.coin_inputs(txn):
            print("From:", prev_txn_out.pub_key.hex(), ", Amount:", prev_txn_out.amount)
        for txn_out in txn.outputs:
            print("To:", txn_out.pub_key.hex(), ", Amount:", txn_out.amount)
