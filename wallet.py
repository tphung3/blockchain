import os
from dataclasses import dataclass
from typing import List, Tuple
from chain import BlockChain
from transaction import Transaction, TxnInput, TxnOutput, LinkedTransaction, LinkedTxnInput
import crypto
import network_util


DEFAULT_OUT_TXN_FILE = os.path.join(os.path.dirname(__file__), "wallet", "pending-txns.txt")


@dataclass
class LocalTxn:
    from_pub_key: bytes
    to_pub_key: bytes
    amount: int

    def __repr__(self):
        if self.from_pub_key is None:
            return f"COINBASE to {self.to_pub_key.hex()[:8]} for {self.amount}"
        else:
            return f"{self.from_pub_key.hex()[:8]} sent {self.to_pub_key.hex()[:8]} {self.amount}"


@dataclass
class Balance:
    involved_txns: List[LocalTxn]
    total: int


class Wallet:
    def __init__(self, pub_key: bytes, pri_key: bytes, out_txn_file=DEFAULT_OUT_TXN_FILE):
        self.pub_key = pub_key
        self.pri_key = pri_key

        self.out_txn_file = out_txn_file
        # create file
        os.makedirs(os.path.dirname(out_txn_file), exist_ok=True)
        open(out_txn_file, 'w').close()

        self.peers: List[network_util.Peer] = []
        self.transactions: List[LinkedTransaction] = []
        self.pending_transactions: List[LinkedTransaction] = []
    
    def find_peers(self):
        self.peers = network_util.find_peers()
        return self.peers
    
    def add_pending(self, txn: LinkedTransaction):
        self.pending_transactions.append(txn)
    
    def get_balance(self, transactions: List[LinkedTransaction]) -> Balance:
        involved_txns = []
        balance = 0

        for txn in transactions:
            involved = False

            sender_pubkey = None
            receiver_pubkey = None
            amount = 0
            
            for coin in txn.coin_inputs():
                sender_pubkey = coin.pub_key
                
                if coin.pub_key == self.pub_key:
                    involved = True
            
            for coin in txn.outputs:
                if coin.pub_key != sender_pubkey:
                    receiver_pubkey = coin.pub_key
                    amount = coin.amount
            
                if coin.pub_key == self.pub_key:
                    involved = True
                
                if coin.pub_key == self.pub_key and not coin.spent:
                    balance += coin.amount
            
            if involved:
                involved_txns.append(LocalTxn(sender_pubkey, receiver_pubkey, amount))
        
        return Balance(involved_txns, balance)
    
    def load_transactions(self, transactions: List[LinkedTransaction]) -> None:
        self.transactions = []

        for txn in transactions:
            for txn_out in txn.outputs:
                if txn_out.pub_key == self.pub_key and not txn_out.spent:
                    self.transactions.append(txn)
                    break

    def find_coins(self, target_amount) -> Tuple[LinkedTransaction, int]:
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
            inputs.append(LinkedTxnInput(txn, txn.txn_id, i))
        
        outputs = [TxnOutput(target_pub_key, target_amount)]
        rem = tot - target_amount
        if rem > 0:
            outputs.append(TxnOutput(self.pub_key, rem))
        
        txn = LinkedTransaction(inputs, outputs)
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
