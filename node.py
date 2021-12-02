#!/usr/bin/env python3

import re
import sys
import os
import time
import socket
import select
import threading
from copy import deepcopy
from chain import BlockChain
import rules
from block import Block
from transaction import Transaction
from wallet import Wallet
from miner import Miner
import network_util

NUM_PEERS = 4

TXN_QUEUE = []      # from network and wallet – used by miner
BLOCK_QUEUE = []    # from network and miner – used by main and miner
REQUEST_QUEUE = []  # from network – used by main
OUT_QUEUE = []      # from main, wallet, and miner – used by network

txn_queue_lock = threading.Lock()
block_queue_lock = threading.Lock()
request_queue_lock = threading.Lock()
out_queue_lock = threading.Lock()

CHAIN = BlockChain()        # modified by main – used by all
CHAIN_MODIFIED = False      # set by main – reset by miner

chain_lock = threading.Lock()
chain_modified_lock = threading.Lock()


def send_catalog_updates(pub_key, port):
    # send update every minute
    while True:
        start = time.time()
        network_util.send_catalog_update(pub_key, port)
        time.sleep(60 - (time.time() - start))


def run_wallet(wallet: Wallet):
    global TXN_QUEUE, OUT_QUEUE

    while line := input("> "):
        args = line.split()
        
        cmd = args[0].lower()

        if cmd == "send":
            pubkey = bytes.fromhex(args[1].lower())
            amount = int(args[2])
            with chain_lock:
                transactions = deepcopy(list(CHAIN.transactions.values()))
            
            wallet.load_transactions(transactions)
            txn = wallet.create_txn(pubkey, amount)

            if txn is None:
                print("failed")
                continue
            
            print(txn.to_json())
            
            with txn_queue_lock:
                TXN_QUEUE.append(txn)
            with out_queue_lock:
                OUT_QUEUE.append(txn.to_message())
        
        elif cmd == "balance":
            with chain_lock:
                transactions = deepcopy(list(CHAIN.transactions.values()))
            
            balance = wallet.get_balance(transactions)

            for txn in balance.involved_txns:
                print('   ', txn)
            
            print("Balance:", balance.total)

        elif cmd == "peers":
            all_peers = network_util.find_peers()
            print("List of all available peers to send coins to:")
            for peer in all_peers:
                print(f"Name: {peer['owner']}, public key: {peer['pub_key']}")

        else:
            print("invalid command:", cmd)


def accept_txns(miner: Miner, chain: BlockChain, pool: list, used: list):
    global CHAIN_MODIFIED, TXN_QUEUE

    miner.reset_pending_txns()
    s = time.time()

    while True:
        # accept incoming txns until timeout, max txn count, or chain modification

        if CHAIN_MODIFIED:
            with chain_modified_lock:
                # unset flag
                CHAIN_MODIFIED = False

            return False

        # timeout
        if time.time() - s >= rules.MINER_WAIT_TIMEOUT:
            # more than just coinbase txn
            if miner.num_pending_txns() > 1:
                return True

            # keep waiting, but refresh timeout
            s = time.time()

        with txn_queue_lock:
            while TXN_QUEUE:
                txn = TXN_QUEUE.pop(0)
                pool.append(txn)
                used.append(False)
                print('added', txn, 'to pool')

        for i, txn in enumerate(pool):
            if used[i]:
                continue

            print("looking at", txn)

            if not chain.verify_transaction(txn):
                print("bad txn, removing from pool")
                # discard invalid txn
                pool.pop(i)
                used.pop(i)
                continue

            print("adding txn to block")
            used[i] = True
            miner.add_pending_txn(txn)
            chain.apply_transaction(txn)

            if miner.num_pending_txns() >= rules.MAX_TXN_COUNT:
                return True


def find_nonce(miner: Miner, chain: BlockChain, pool: list, used: list):
    global CHAIN_MODIFIED, BLOCK_QUEUE, OUT_QUEUE
    print("started mining")

    chain_head = chain.head_block.data
    block = miner.compose_block(chain_head.block_hash, chain_head.height + 1)

    miner.first_nonce()
    while nonce := miner.next_nonce():
        if miner.valid_nonce(block, nonce):
            block.set_nonce(nonce)

            print("found nonce!")
            print("block:", block.to_json())

            with block_queue_lock:
                BLOCK_QUEUE.append(block)
            with out_queue_lock:
                OUT_QUEUE.append(block.to_message())

            # remove txns used in block
            pool = [txn for i, txn in enumerate(pool) if not used[i]]
            used = [False for _ in pool]

            return True

        # invalid nonce + chain has been modified
        elif CHAIN_MODIFIED:
            for i in range(len(used)):
                # unmark all txns in pool
                used[i] = False

            with chain_modified_lock:
                # unset flag
                CHAIN_MODIFIED = False

            return False


def run_miner(miner: Miner):
    global CHAIN

    pool = []   # pool of txns to mine
    used = []   # flag for each txn (if in current mining block)

    while True:
        with chain_lock:
            # checkout current state of chain
            chain = deepcopy(CHAIN)
            print('copied chain')
        
        if not accept_txns(miner, chain, pool, used):
            continue

        find_nonce(miner, chain, pool, used)


           
def run_network(main_socket):
    #get all peers' information before doing anything else
    all_peers = network_util.find_peers()

    #dict of outward TCP sockets (only for sending messages to other peers)
    out_sockets = []

    #set up a TCP connection to each peer 
    for peer in all_peers:
        out_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        out_address = (peer['address'], int(peer['port']))
        out_socket.connect(out_address)
        out_sockets.append(out_socket)
    
    sockets = set()
    while True:
        #listen phase
        inputs = [main_socket] + list(sockets)
        readable, _, _ = select.select(inputs, [], [])
        for s in readable:
            if s == main_socket:
                # main socket -> accept new connection
                conn, _ = main_socket.accept()
                sockets.add(conn)
                print("Accepted a connection")
            else:
                # other socket -> handle request
                try:
                    req = network_util.rec_json(s)
                    if req is None:
                        print("Client closed the connection")
                        s.close()
                        sockets.remove(s)
                        continue

                    handle_request(req)

                except ValueError:
                    # good request, but invalid JSON -> send error msg and return
                    pass # self.send_error(s, -1, "Request was not in JSON format")

        #speak phase
        with out_queue_lock:
            if len(OUT_QUEUE) > 0:
                while (len(OUT_QUEUE) > 0):
                    out_req = OUT_QUEUE[0]
                    handle_out_request(out_sockets, out_req)
                    OUT_QUEUE.pop(0)
            else:
                pass

#handle 3 types of outgoing requests: transactions, blocks, and request blocks
def handle_out_request(out_sockets, out_req):
    out_req_type = out_req.get("type", None)
    if out_req_type == "block" or out_req_type == "transaction":
        for out_socket in out_sockets:
            network_util.send_json(out_socket, out_req.get("data"))
    else:
        pass

#handle 3 types of incoming requests: transactions, blocks, and request blocks
def handle_request(req):
    request_type = req.get("type", None)
    if request_type == "block":
        with block_queue_lock:
            BLOCK_QUEUE.append(Block.from_json(req.get("data")))
    elif request_type == "transaction":
        with txn_queue_lock:
            TXN_QUEUE.append(Transaction.from_json(req.get("data")))
    elif request_type == "block_requests":
        #TODO
        pass
    else:
        #TODO
        pass


class ChainServer:
    def __init__(self, pub_key, pri_key):
        self.pub_key = pub_key
        self.pri_key = pri_key
        
        # TODO: initialize blockchain object
        
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    @staticmethod
    def send_error(conn, code, msg):
        network_util.send_json(conn, {
            "status": "error",
            "error_code": code,
            "error_msg": msg
        })

    def run(self):
        self.socket.bind(('', 0))
        _, self.port = self.socket.getsockname()

        self.socket.listen(8)
        print("Listening on port", self.port)

        # send catalog updates in background
        threading.Thread(target=send_catalog_updates, args=(self.pub_key, self.port), daemon=True).start()

        #send network interface in background
        threading.Thread(target=run_network, args=(self.socket), daemon=True).start()


def usage(status):
    print(f"{sys.argv[0]} NAME")
    sys.exit(status)


def main():
    if len(sys.argv) < 2:
        pass # usage(1)
    
    import crypto
    pub_key = crypto.load_public_key()
    pri_key = crypto.load_private_key()

    """
    miner = Miner(pub_key, pri_key)
    from transaction import Transaction
    # good txns
    txn_list = [{"txn_id": "1f7fde67c75b03ceea8d745aeb82c0ce127f667992cc710f970dc3a90abd63d4", "inputs": [{"txn_id": "06eeaf748440eccc5fe44bc53b3c032b183b57f4274361484e4fbea508ebc872", "index": 0}], "outputs": [{"pub_key": "61626364", "amount": 40, "signature": "5061e1f8c8fe507381dfee844b5def68c8c570f290807032ff13b844cf4eeb15a111fa4b41b08f31e1d9bcc951f023d7aeb23d00917d6eb1f0e14a4f8b57a640"}, {"pub_key": "fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166", "amount": 10, "signature": "83e237ce72a5f68c9fb87bace4aef2a025e6e6651d4f346925b71148a5c1ff725b7cc2e21b5e68f43b22da24e58aace447ee471b09d7eb0a692c88d5103543bc"}]},{"txn_id": "ae1d53dc68663e84e56cdb77c2ea0c15eddaa177427e2662fc070306801005bd", "inputs": [{"txn_id": "1f7fde67c75b03ceea8d745aeb82c0ce127f667992cc710f970dc3a90abd63d4", "index": 1}], "outputs": [{"pub_key": "61626364", "amount": 5, "signature": "98a2b03835c6a0068f4bb04710314f49b8cdb45866969a35e389ff38206d17ce6fb1808c0b3080b231430e11a94b9b6db5c24bef4a68433a9bd1edbbfc2ec2de"}, {"pub_key": "fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166", "amount": 5, "signature": "71c4d43a9d9c82b1d848119da1c2d1fe80fd62590635398d05e4060239a40a36906661136f0277bfd0efc10c8cf619cbeea22fcee922af744f776869afc75cf0"}]},{"txn_id": "335f9b62e474e4cb44876f249e380edad06f7a353c1323acf8fb9488f72ff8f6", "inputs": [{"txn_id": "ae1d53dc68663e84e56cdb77c2ea0c15eddaa177427e2662fc070306801005bd", "index": 1}], "outputs": [{"pub_key": "61626364", "amount": 4, "signature": "5f5155d1a28fd1d586b336b248dd83e224535e22b5ab534e3668b7d023cef9011d1c1f7ca7ed8c845c51493452e782420f08ea4d064ae7f0354f4dae2deb06ce"}, {"pub_key": "fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166", "amount": 1, "signature": "3a45b96c71c1eed88f84c1abe732c77138403b582c7e8a70549e6f17ba05419d4725a83c7f93afc1d45a0b727d25b820e4e85e40ca1051c9ca17003efccf5d1c"}]}]
    # bad txns
    #txn_list = [{"txn_id": "5122c29da194036aab00f4bf7f621eee7e76174451c8bc6443098c3a07fd2d83", "inputs": [{"txn_id": "06eeaf748440eccc5fe44bc53b3c032b183b57f4274361484e4fbea508ebc872", "index": 0}], "outputs": [{"pub_key": "61626364", "amount": 40, "signature": "5bee4ed879a21187296f0cb7fce8d17f2fd19f2085c09678b8843ad6760ddca3e32b2a18bb4d48b45e3f87dd631c4f5d8fa536ecfdd2bbed735e2cbb45d040cc"}, {"pub_key": "fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166", "amount": 10, "signature": "e5488af8c44712759029ca6ddcac1931a42c32936f3f9549346a346ce98c907aa39c009e3b8b4abf95d68a8c178d86523a145777e643a6a0c99d4069bfb74484"}]},{"txn_id": "b4b531ef5c132b32cd4eaa5fbe3193edc35de8fe1a538c6b36ab3782e5d81ee2", "inputs": [{"txn_id": "5122c29da194036aab00f4bf7f621eee7e76174451c8bc6443098c3a07fd2d83", "index": 1}], "outputs": [{"pub_key": "61626364", "amount": 5, "signature": "1d80c0ca4415fadc70d8e49f3e45902f1a71b3ce1a642dc2aee240045e692fcb06614958d070afeb37d614deedfc48112417e55ef34f0d7b94dedd59b027c54d"}, {"pub_key": "fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166", "amount": 5, "signature": "b0236664094cd22c62644f3b2c319c4757d0e4f6ce6439ca4830c88ef74bed712c1c09d4afdfa79c319111d692de42bccbcf93cb5578a6539a271170a22fb594"}]},{"txn_id": "1425210b148c3cd714c78313ab52ddfe57496418ceefa1b073b758f7a29b2bda", "inputs": [{"txn_id": "b4b531ef5c132b32cd4eaa5fbe3193edc35de8fe1a538c6b36ab3782e5d81ee2", "index": 1}], "outputs": [{"pub_key": "61626364", "amount": 10, "signature": "43d2a1f3e3bd033b55ff749dbb1efd30b02858d4085246ff71768dc44cc390b23140912067876354445ea462f50eede242eb0076e4504c9ca563c92efd92922a"}]}]
    txns = [Transaction.from_json(txn_json) for txn_json in txn_list]
    global TXN_QUEUE
    with txn_queue_lock:
        TXN_QUEUE = txns
    run_miner(miner)
    """
    
    block = Block.from_json({'hash': '0000029fe2de502979b5b1e345ff58b4c47f9f872c26999bc47752930a8a5f76', 'prev_hash': '00000e9f2fb735130801b4c31e40c3b9c6fa0789a13f8c5d685cd1602c97bafb', 'height': 1, 'nonce': 66240216508772406228315848838552293799641861242416215840665602550228984815026, 'transactions': [{'txn_id': 'adbcd37eb20dfe3cfe174358ac32c6b2da4027ea48ffd47e9af73689f4dc015f', 'inputs': [], 'outputs': [{'pub_key': 'fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166', 'amount': 50, 'signature': '108f9bdcb45f3823b78a76344fcb1c9cbfe3dbdb1fbc6869c52fd0c84ffae25f116d7253034e753171da1b0dab186cc1c0af656969379451308172a1311e5ed8'}]}, {'txn_id': '1f7fde67c75b03ceea8d745aeb82c0ce127f667992cc710f970dc3a90abd63d4', 'inputs': [{'txn_id': '06eeaf748440eccc5fe44bc53b3c032b183b57f4274361484e4fbea508ebc872', 'index': 0}], 'outputs': [{'pub_key': '61626364', 'amount': 40, 'signature': '5061e1f8c8fe507381dfee844b5def68c8c570f290807032ff13b844cf4eeb15a111fa4b41b08f31e1d9bcc951f023d7aeb23d00917d6eb1f0e14a4f8b57a640'}, {'pub_key': 'fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166', 'amount': 10, 'signature': '83e237ce72a5f68c9fb87bace4aef2a025e6e6651d4f346925b71148a5c1ff725b7cc2e21b5e68f43b22da24e58aace447ee471b09d7eb0a692c88d5103543bc'}]}, {'txn_id': 'ae1d53dc68663e84e56cdb77c2ea0c15eddaa177427e2662fc070306801005bd', 'inputs': [{'txn_id': '1f7fde67c75b03ceea8d745aeb82c0ce127f667992cc710f970dc3a90abd63d4', 'index': 1}], 'outputs': [{'pub_key': '61626364', 'amount': 5, 'signature': '98a2b03835c6a0068f4bb04710314f49b8cdb45866969a35e389ff38206d17ce6fb1808c0b3080b231430e11a94b9b6db5c24bef4a68433a9bd1edbbfc2ec2de'}, {'pub_key': 'fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166', 'amount': 5, 'signature': '71c4d43a9d9c82b1d848119da1c2d1fe80fd62590635398d05e4060239a40a36906661136f0277bfd0efc10c8cf619cbeea22fcee922af744f776869afc75cf0'}]}, {'txn_id': '335f9b62e474e4cb44876f249e380edad06f7a353c1323acf8fb9488f72ff8f6', 'inputs': [{'txn_id': 'ae1d53dc68663e84e56cdb77c2ea0c15eddaa177427e2662fc070306801005bd', 'index': 1}], 'outputs': [{'pub_key': '61626364', 'amount': 4, 'signature': '5f5155d1a28fd1d586b336b248dd83e224535e22b5ab534e3668b7d023cef9011d1c1f7ca7ed8c845c51493452e782420f08ea4d064ae7f0354f4dae2deb06ce'}, {'pub_key': 'fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166', 'amount': 1, 'signature': '3a45b96c71c1eed88f84c1abe732c77138403b582c7e8a70549e6f17ba05419d4725a83c7f93afc1d45a0b727d25b820e4e85e40ca1051c9ca17003efccf5d1c'}]}]})
    CHAIN.insert_block(block)
    wallet = Wallet(pub_key, pri_key)
    run_wallet(wallet)


if __name__ == "__main__":
    main()
