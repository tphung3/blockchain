import json
from dataclasses import dataclass, asdict
from typing import List
import crypto


MAX_TXN_COUNT = 10


class Serializable:
    @classmethod
    def from_json(cls, json_data):
        raise NotImplementedError

    def to_json(self):
        raise NotImplementedError

    def to_bytes(self):
        return json.dumps(self.to_json()).encode()


@dataclass
class TxnInput(Serializable):
    txn_id: bytes
    index: int

    @classmethod
    def from_json(cls, json_data):
        attrs = ('txn_id', 'index')
        for attr in attrs:
            if json_data.get(attr) is None:
                return None

        return TxnInput(bytes.fromhex(json_data['txn_id']), json_data['index'])

    def to_json(self):
        return {
            "txn_id": self.txn_id.hex(),
            "index": self.index
        }


class TxnOutput(Serializable):
    def __init__(self,
            pub_key: bytes,
            amount: int,
            signature: bytes = None):
        
        self.pub_key = pub_key
        self.amount = amount
        self.signature = signature

        # for blockchain usage
        self.spent = False

    @classmethod
    def from_json(cls, json_data):
        attrs = ('pub_key', 'amount', 'signature')
        for attr in attrs:
            if json_data.get(attr) is None:
                return None

        return TxnOutput(bytes.fromhex(json_data['pub_key']), json_data['amount'], bytes.fromhex(json_data['signature']))

    def to_json(self):
        return {
            "pub_key": self.pub_key.hex(),
            "amount": self.amount,
            "signature": "" if self.signature is None else self.signature.hex()
        }


class Transaction(Serializable):
    def __init__(self, inputs: List[TxnInput], outputs: List[TxnOutput], txn_id: bytes = None):
        self.inputs = inputs
        self.outputs = outputs
        self.txn_id = txn_id

    @classmethod
    def from_json(cls, json_data):
        attrs = ('txn_id', 'inputs', 'outputs')
        for attr in attrs:
            if json_data.get(attr) is None:
                return None
        
        txn_id = bytes.fromhex(json_data['txn_id'])
        inputs = [TxnInput.from_json(txn_in) for txn_in in json_data['inputs']]
        outputs = [TxnOutput.from_json(txn_out) for txn_out in json_data['outputs']]
        if not all(inputs) or not all(outputs):
            return None
        
        return Transaction(inputs, outputs, txn_id=txn_id)

    def to_json(self):
        return {
            "txn_id": "" if self.txn_id is None else self.txn_id.hex(),
            "inputs": [txn_in.to_json() for txn_in in self.inputs],
            "outputs": [txn_out.to_json() for txn_out in self.outputs]
        }
    
    def to_message(self):
        return {
            "type": "transaction",
            "data": self.to_json()
        }
    
    def sign(self, sender_private_key: bytes):
        txn_in_bytes = b''

        for txn_in in self.inputs:
            txn_in_bytes += txn_in.to_bytes()
        
        for txn_out in self.outputs:
            txn_bytes = crypto.double_sha256(txn_in_bytes + txn_out.pub_key)
            txn_out.signature = crypto.sign(sender_private_key, txn_bytes)
        
        self.txn_id = self.compute_txn_id()
    
    def verify_signature(self, sender_pubkey: bytes):
        txn_in_bytes = b''

        for txn_in in self.inputs:
            # assume all txn_in's pubkey matches sender_pubkey
            txn_in_bytes += txn_in.to_bytes()

        for txn_out in self.outputs:
            txn_bytes = crypto.double_sha256(txn_in_bytes + txn_out.pub_key)
            if not crypto.verify(sender_pubkey, txn_out.signature, txn_bytes):
                return False
        
        return True
    
    def compute_txn_id(self):
        data = b''
        data += json.dumps([txn_in.to_json() for txn_in in self.inputs]).encode()
        data += json.dumps([txn_out.to_json() for txn_out in self.outputs]).encode()
        return crypto.double_sha256(data)


class LinkedTxnInput(TxnInput):
    def __init__(self, txn: 'LinkedTransaction', txn_id: bytes, index: int):
        self.txn = txn
        self.txn_id = txn_id
        self.index = index
    
    @classmethod
    def link(cls, txn_in: TxnInput, txn: 'LinkedTransaction'):
        return cls(txn, txn_in.txn_id, txn_in.index)


class LinkedTransaction(Transaction):
    def __init__(self, inputs: List[LinkedTxnInput], outputs: List[TxnOutput], txn_id: bytes = None):
        self.inputs = inputs
        self.outputs = outputs
        self.txn_id = txn_id
    
    @classmethod
    def link(cls, txn: Transaction, inputs: List[LinkedTxnInput]):
        return cls(inputs, txn.outputs, txn.txn_id)
    
    def coin_inputs(self) -> List[TxnOutput]:
        coins = []
        for txn_in in self.inputs:
            coins.append(txn_in.txn.outputs[txn_in.index])
        return coins


if __name__ == "__main__":
    txn_in = TxnInput(b'\xe330', 0)
    txn_out = TxnOutput(b'3dbad', 50)

    txn = Transaction([txn_in], [txn_out])
    txn.txn_id = txn.compute_txn_id()

    txn2 = Transaction.from_json(txn.to_json())

    assert txn.to_json() == txn2.to_json()
    print(txn.to_json())

