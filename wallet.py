from io import DEFAULT_BUFFER_SIZE
from dataclasses import dataclass
from typing import List, Tuple
import datetime
from transaction import Transaction, TxnInput, TxnOutput
import crypto
import os


DEFAULT_OUT_TXN_FILE = os.path.join(os.path.dirname(__file__), "wallet", "outgoing-txns.txt")


@dataclass
class LocalTxn:
    txn: Transaction
    timestamp: datetime.datetime


@dataclass
class Peer:
    pub_key: bytes
    display_name: str



class Wallet:
    def __init__(self, pub_key: bytes, pri_key: bytes, out_txn_file=DEFAULT_OUT_TXN_FILE):
        self.pub_key = pub_key
        self.pri_key = pri_key

        self.out_txn_file = out_txn_file
        # create file
        os.makedirs(os.path.dirname(out_txn_file), exist_ok=True)
        open(out_txn_file, 'w').close()

        self.peers = []
        self.transactions: List[Transaction] = []

    
    def load_transactions(self, transactions: List[Transaction]) -> None:
        for txn in transactions:
            for txn_out in txn.outputs:
                if txn_out.pub_key == self.pub_key:
                    self.transactions.append(txn)
                    break

    def find_coins(self, target_amount) -> Tuple[Transaction, int]:
        tot = 0
        in_txns = []

        for txn in self.transactions:
            for i, coin in enumerate(txn.outputs):
                if coin.pub_key != self.pub_key:
                    # not mine
                    continue

                if coin.spent:
                    # already spent
                    continue

                tot += coin.amount
                in_txns.append((txn, i))

                if tot >= target_amount:
                    return in_txns
        
        return []
    
    def create_txn(self, target_pub_key, target_amount):
        txns = self.find_coins(target_amount)
        if not txns:
            return None
        
        tot = 0
        inputs = []
        for (txn, i) in txns:
            tot += txn.outputs[i].amount
            inputs.append(TxnInput(txn.txn_id, i))
        
        outputs = [TxnOutput(target_pub_key, target_amount)]
        rem = tot - target_amount
        if rem > 0:
            outputs.append(TxnOutput(self.pub_key, rem))
        
        txn = Transaction(inputs, outputs)
        txn.sign(self.pri_key)
        return txn
    
    def save_out_txn(self, txn: Transaction):
        with open(self.out_txn_file, 'a') as stream:
            print(txn.to_json(), file=stream)


if __name__ == "__main__":
    pub_key = crypto.load_public_key()
    pri_key = crypto.load_private_key()
    
    from chain import BlockChain
    chain = BlockChain()

    wallet = Wallet(pub_key, pri_key)
    wallet.load_transactions(chain.head_block.data.transactions)

    # send abcd 40 coins
    txn1 = wallet.create_txn(b'abcd', 40)

    # send abcd 5 coins
    txn2_in = [TxnInput(txn1.txn_id, 1)]
    txn2_out = [TxnOutput(b'abcd', 5), TxnOutput(pub_key, 5)]
    txn2 = Transaction(txn2_in, txn2_out)
    txn2.sign(pri_key)

    # send abcd 4 coins
    txn3_in = [TxnInput(txn2.txn_id, 1)]
    txn3_out = [TxnOutput(b'abcd', 4), TxnOutput(pub_key, 1)]
    txn3 = Transaction(txn3_in, txn3_out)
    txn3.sign(pri_key)

    # add to chain
    chain.apply_transaction(txn1)
    chain.apply_transaction(txn2)
    chain.apply_transaction(txn3)

    wallet2 = Wallet(b'abcd', b'')
    wallet2.load_transactions(chain.head_block.data.transactions)

    import json
    print(json.dumps(txn1.to_json()))
    print(json.dumps(txn2.to_json()))
    print(json.dumps(txn3.to_json()))
