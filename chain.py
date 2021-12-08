import os
import sys
import json
from dataclasses import dataclass
from typing import List
import rules
from utils import get_logger
from block import Block
from transaction import Transaction, LinkedTxnInput, LinkedTransaction


STORAGE_DIR = os.path.join(os.path.dirname(__file__), "chain")


@dataclass
class BlockChainNode:
    prev: 'BlockChainNode'
    data: Block


class BlockChain:
    def __init__(self, storage_dir=STORAGE_DIR):
        self.storage_dir = storage_dir

        self.levels = []             # level  -> { block_hash -> BlockChainNode }
        self.transactions = dict()   # txn_id -> LinkedTransaction

        self.max_height = 0
        
        self.logger = get_logger()

        # load genesis block
        genesis_level = self.load_block_file(0)
        if not genesis_level:
            self.logger.error("Invalid/Missing Genesis Block")

        self.head_block = genesis_level[0]
        if not self.insert_block(self.head_block):
            self.logger.error("Invalid Genesis Block")
    
    def load_chain(self):
        # load at best effort after genesis block
        height = 1
        while blocks := self.load_block_file(height):
            self.logger.debug("Loading all blocks at height " + str(height))
            for block in blocks:
                self.insert_block(block)
            height += 1

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
                    self.logger.error(f'invalid block on line {i} of {block_file}')
                    continue
                blocks.append(block)
        
        if level == 0 and len(blocks) != 1:
            # incorrect number of genesis blocks
            self.logger.error(f'{block_file} has the incorrect number of blocks for a genesis block')
            return None
        
        return blocks

    def save_block_to_file(self, block: Block) -> None:
        block_file = os.path.join(self.storage_dir, str(block.height))

        with open(block_file, 'a') as stream:
            block_str = json.dumps(Block.to_json(block))
            print(block_str, file=stream)
            stream.flush()

    def previous_block_node(self, block: Block) -> BlockChainNode:
        """
        Returns the previous block chain node, which block.prev_hash references (None if no such hash exists)
        """
        return None if (block.height <= 0 or block.height > len(self.levels)) else self.levels[block.height - 1].get(block.prev_hash)

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

        # load additional levels if necessary
        diff = block_node.data.height - len(self.levels) + 1
        for _ in range(diff):
            self.levels.append(dict())
        
        if block_node.prev:
            self.move_head(self.head_block, block_node.prev)

        if not self.verify_block(block_node.data):
            # invalid block, reject
            return False
        
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
            self.apply_transaction(txn)
    
    def apply_transaction(self, txn: Transaction) -> None:
        """
        Apply transaction to chain, linking it to its predecessor accordingly
        """
        linked_txn_inputs = []
        for txn_in in txn.inputs:
            assert txn_in.txn_id in self.transactions
            # get from pool
            linked_txn = self.transactions[txn_in.txn_id]

            # link to incoming txn object
            linked_txn_inputs.append(LinkedTxnInput.link(txn_in, linked_txn))

            # spend coin
            linked_txn.outputs[txn_in.index].spent = True
        
        for txn_out in txn.outputs:
            # ensure each coin is unspent when we add it to the chain
            txn_out.spent = False
        
        linked_txn = LinkedTransaction.link(txn, linked_txn_inputs)
        self.transactions[linked_txn.txn_id] = linked_txn

    def revert_block(self, block_node: BlockChainNode) -> None:
        """
        Undo a block

        Assumptions:
            - all txns in `block_node` have been applied
        """
        for txn in reversed(block_node.data.transactions):
            self.revert_transaction(txn)
    
    def revert_transaction(self, txn: Transaction) -> None:
        linked_txn = self.transactions.pop(txn.txn_id)

        for linked_txn_in in linked_txn.inputs:
            # unspend coin
            linked_txn_in.txn.outputs[linked_txn_in.index].spent = False
    
    def move_head(self, src: BlockChainNode, dst: BlockChainNode) -> BlockChainNode:
        """
        Moves head of chain from one node to another
        """
        to_apply = []

        # revert back to LCA
        while src.data.height > dst.data.height:
            self.revert_block(src)
            src = src.prev
        while dst.data.height > src.data.height:
            to_apply.append(dst)
            dst = dst.prev

        while src.data.block_hash != dst.data.block_hash and src and dst:
            self.revert_block(src)
            to_apply.append(dst)
            src = src.prev
            dst = dst.prev

        # all blocks should at least meet at genesis
        assert src.data.block_hash == dst.data.block_hash

        # move up to target
        for block in reversed(to_apply):
            self.apply_block(block)

    def verify_block(self, block: Block) -> bool:
        if block.height < 0:
            self.logger.warn('invalid block height for block ' + block.block_hash.hex())
            return False
        
        h = block.compute_hash()

        if block.block_hash != h:
            self.logger.warn('incorrect hash for block ' + block.block_hash.hex())
            return False

        if not rules.valid_block_hash(h):
            self.logger.warn('invalid hash for' + block.block_hash.hex())
            return False

        if len(block.transactions) < 1:
            self.logger.warn('no transactions for ' + block.block_hash.hex())
            return False
        
        invalid_txns = False
        to_revert = []

        for i, txn in enumerate(block.transactions):
            # first txn is a coinbase txn
            is_coinbase = (i == 0)

            if not self.verify_transaction(txn, is_coinbase):
                self.logger.warn('unable to verify transaction ' + txn.txn_id.hex() + ' for ' + block.block_hash.hex())
                invalid_txns = True
                break
            
            # temporary apply transaction
            self.apply_transaction(txn)
            to_revert.append(txn)
        
        for txn in reversed(to_revert):
            # revert all applied transactions
            self.revert_transaction(txn)
        
        if invalid_txns:
            return False

        return True

    def verify_transaction(self, txn: Transaction, is_coinbase: bool = False) -> bool:
        if txn.txn_id in self.transactions:
            self.logger.warn('duplicate transaction')
            return False
        
        if txn.txn_id != txn.compute_txn_id():
            self.logger.warn('invalid hash')
            return False
        
        sender_pubkey = None
        in_tot = 0

        if is_coinbase:
            if len(txn.inputs) != 0 or len(txn.outputs) != 1:
                self.logger.warn('invalid coinbase')
                return False
            sender_pubkey = txn.outputs[0].pub_key
        
        for txn_in in txn.inputs:
            if txn_in.txn_id not in self.transactions:
                self.logger.warn('incoming txn does not exist')
                return False
            
            prev_txn = self.transactions[txn_in.txn_id]

            if txn_in.index < 0 or txn_in.index >= len(prev_txn.outputs):
                self.logger.warn('invalid index')
                return False
            
            prev_coin = prev_txn.outputs[txn_in.index]

            if sender_pubkey is None:
                sender_pubkey = prev_coin.pub_key
            elif sender_pubkey != prev_coin.pub_key:
                self.logger.warn('all incoming not from same peer')
                return False
            
            if prev_coin.spent:
                self.logger.warn('coin already spent')
                return False

            in_tot += prev_coin.amount
        
        out_tot = 0
        for out_txn in txn.outputs:
            if out_txn.amount < 0:
                self.logger.warn('invalid amount')
                return False
            
            out_tot += out_txn.amount
        
        if not is_coinbase and in_tot != out_tot:
            self.logger.warn('mismatching amounts')
            return False
        
        if not txn.verify_signature(sender_pubkey):
            self.logger.warn('invalid signature')
            return False
        
        return True


if __name__ == "__main__":
    bc = BlockChain()
    print("initialized chain with genesis block:")
    print(json.dumps(bc.head_block.data.to_json(), indent=2))
    print("Transactions:")
    for txn_id, txn in bc.transactions.items():
        print("TXN ID:", txn_id.hex())
        for prev_txn_out in txn.coin_inputs():
            print("From:", prev_txn_out.pub_key.hex(), ", Amount:", prev_txn_out.amount)
        for txn_out in txn.outputs:
            print("To:", txn_out.pub_key.hex(), ", Amount:", txn_out.amount)
