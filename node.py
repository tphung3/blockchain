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
    global TXN_QUEUE, OUT_QUEUE, CHAIN

    while line := input("> "):
        args = line.split()
        
        cmd = args[0].lower()

        if cmd == "send":
            pubkey = bytes.fromhex(args[1].lower())
            amount = int(args[2])
            txn = wallet.create_txn(pubkey, amount)

            if txn is None:
                print("failed")
            
            with txn_queue_lock:
                TXN_QUEUE.append(txn)
            with out_queue_lock:
                OUT_QUEUE.append(txn.to_message())
        
        elif cmd == "balance":

			#get all txns
            all_txns = CHAIN.transactions
			
			#let wallet load all txns where wallet is payee
			wallet.load_transactions(all_txns)
			coin_in_txns = wallet.transactions

			#find all txns where wallet is payer
			coin_out_txns = []
			for txn in all_txns:
				for txn_in in txn.inputs:
					if txn_in.pub_key == wallet.pub_key:
						coin_in_txns.append(txn)

			#the balance should be the difference between total coins in and total coins out
			total_coins_in = 0
			for txn in coin_in_txns:
				for txn_out in txn:
					if txn_out.pub_key == wallet.pub_key:
						total_coins_in += txn_out.amount
						break

			total_coins_out = 0
			for txn in coin_out_txns:
				for txn_in in txn.inputs:
					if txn_in.pub_key == wallet.pub_key:
						#total_coins_out += 
						pass

        elif cmd == "history":
            pass

        elif cmd == "peers":
            all_peers = network_util.get_peers()
            print("List of all available peers to send coins to:")
            for peer in all_peers:
                print(f"Name: {peer['owner']}, public key: {peer['pub_key']}")

        else:
            print("invalid command:", cmd)


def run_miner(miner: Miner):
    global CHAIN, CHAIN_MODIFIED, BLOCK_QUEUE, OUT_QUEUE

    pool = []   # pool of txns to mine
    used = []   # flag for each txn (if in current mining block)

    while True:
        s = time.time()

        with chain_lock:
            # checkout current state of chain
            chain = deepcopy(CHAIN)
            print('copied chain')

        start_mining = False
        miner.reset_pending_txns()

        while True:
            # accept incoming txns until timeout, max txn count, or chain modification

            if CHAIN_MODIFIED:
                with chain_modified_lock:
                    # unset flag
                    CHAIN_MODIFIED = False
                # reset mining
                break
            
            # timeout
            if time.time() - s >= rules.MINER_WAIT_TIMEOUT:
                # more than just coinbase txn
                start_mining = (miner.num_pending_txns() > 1)
                break

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
                    start_mining = True
                    break
            else:
                continue
            # exit while loop if break was used to exit for loop
            break
        
        if not start_mining:
            continue

        print("started mining")

        chain_head = chain.head_block.data
        block = miner.compose_block(chain_head.block_hash, chain_head.height + 1)
        
        miner.first_nonce()
        while nonce := miner.next_nonce():
            if miner.valid_nonce(block, nonce):
                block.set_nonce(nonce)

                print("found nonce!")
                print("block:", block)
                
                with block_queue_lock:
                    BLOCK_QUEUE.append(block)
                with out_queue_lock:
                    OUT_QUEUE.append(block.to_message())
                
                # remove txns used in block
                pool = [txn for i, txn in enumerate(pool) if not used[i]]
                used = [False for _ in pool]
                break

            # invalid nonce + chain has been modified
            elif CHAIN_MODIFIED:
                for i in range(len(used)):
                    # unmark all txns in pool
                    used[i] = False
                    
                with chain_modified_lock:
                    # unset flag
                    CHAIN_MODIFIED = False
                
                # restart mining
                break

           
def run_network(main_socket):

	global OUT_QUEUE
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
	
	GLOBAL BLOCK_QUEUE, TXN_QUEUE 

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

        #run network interface in background
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
    miner = Miner(pub_key, pri_key)

    txn_list = [
        {"txn_id": "6f40874fff99062f4c8860d8803eb2b859dbc299fd737237573b55099612e6da", "inputs": [{"txn_id": "06eeaf748440eccc5fe44bc53b3c032b183b57f4274361484e4fbea508ebc872", "index": 0}], "outputs": [{"pub_key": "61626364", "amount": 40, "signature": "940f5d6abd27ae1cd3a8e438c88db5d847c3dcb96828807b61f21e9a210c5a02342e6870a782983697e3e299e2ea3349fb1b55c579c0e631cff3fe730cc3e98e"}, {"pub_key": "fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166", "amount": 10, "signature": "72c252a4c16b70b81962556e76826d96e5841f0a19929a4612333e136e446cd0cb807c7a797c1df68a4e59dda1448669bbc09f894a6808a1119e360b129db261"}]},
        {"txn_id": "c82a104b14116236cf71b3e73b4a00db5aa507d500b5dc342f804b1371e14b63", "inputs": [{"txn_id": "06eeaf748440eccc5fe44bc53b3c032b183b57f4274361484e4fbea508ebc872", "index": 0}], "outputs": [{"pub_key": "61626364", "amount": 5, "signature": "01342433b47ef336ff3edd2850f408bdfbf28e5c56cff080a9ac5a45fb4e3f6bc63f10ac5291076909e2ff948e70f421f6148207e4a5f4da77dcf693ba6f5b7f"}, {"pub_key": "fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166", "amount": 45, "signature": "d5b845ebe5e1ccaa20fcd1bcc2fafa5cbb4b32fe8e20da480d44332d0b1a7181797c7c52b76d742537ad69d18cac454c7acd504be6fb95cccf8336bad0ae467e"}]},
        {"txn_id": "0f3e53367f4d8d67f00393e46cbba3f6f3e32b4eed6f00154667dafef3dd4cee", "inputs": [{"txn_id": "06eeaf748440eccc5fe44bc53b3c032b183b57f4274361484e4fbea508ebc872", "index": 0}], "outputs": [{"pub_key": "61626364", "amount": 4, "signature": "423f608a44503285001f15e48794211aa1fc90e28c48f675ab380a165cba65ed839262ac92deacaa92188890eaf84ad5c67bf139ee645d4e4605572009fbd145"}, {"pub_key": "fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166", "amount": 46, "signature": "a60b851f961bb086bec521a9d78bc29fca23035440fea3d870f13bf3c783bb2d1aff19e6a3aa1f1cfdcef433e5307b17610035cf29cd4e409424b464a3e08b30"}]}
    ]
    from transaction import Transaction
    txns = [Transaction.from_json(txn_json) for txn_json in txn_list]
    global TXN_QUEUE
    with txn_queue_lock:
        TXN_QUEUE = txns
    
    run_miner(miner)

    """
    # TODO: load keys, exit if not exists
    pub_key = None
    pri_key = None

    server = ChainServer(pub_key, pri_key)
    server.run()
    """


if __name__ == "__main__":
    main()

