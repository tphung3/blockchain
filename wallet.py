from typing import List, Tuple
from transaction import Transaction, TxnInput, TxnOutput
import crypto


class Wallet:
    def __init__(self, pub_key: bytes, pri_key: bytes):
        self.pub_key = pub_key
        self.pri_key = pri_key

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


if __name__ == "__main__":
    pub_key = crypto.load_public_key()
    pri_key = crypto.load_private_key()
    
    from chain import BlockChain
    chain = BlockChain()
    wallet = Wallet(pub_key, pri_key)

    wallet.load_transactions(chain.head_block.data.transactions)
    txn = wallet.create_txn(b'abcd', 40)

    import json
    print(json.dumps(txn.to_json()))
