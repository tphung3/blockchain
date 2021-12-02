#!/usr/bin/env python3

import sys
import time
import threading
from copy import deepcopy
import rules
import crypto
import network_util
from chain import BlockChain, BlockChainNode
from block import Block
from transaction import Transaction
from wallet import Wallet
from miner import Miner


TXN_QUEUE = []      # from network and wallet – used by miner
BLOCK_QUEUE = []    # from network and miner – used by main and miner
REQUEST_QUEUE = []  # from network – used by main
OUT_QUEUE = []      # from main, wallet, and miner – used by network

txn_queue_lock = threading.Lock()
block_queue_lock = threading.Lock()
request_queue_lock = threading.Lock()
out_queue_lock = threading.Lock()

CHAIN = None                # modified by main – used by all
CHAIN_MODIFIED = False      # set by main – reset by miner

chain_lock = threading.Lock()
chain_modified_lock = threading.Lock()


def send_catalog_updates(pub_key, port, display_name):
    # send update every minute
    while True:
        start = time.time()
        network_util.send_catalog_update(pub_key, port, display_name)
        time.sleep(60 - (time.time() - start))


def run_wallet(wallet: Wallet):
    global TXN_QUEUE, OUT_QUEUE, CHAIN

    while True:
        try:
            line = input("> ")
        except EOFError:
            return

        args = line.split()
        if not args:
            continue
        cmd = args[0].lower()

        if cmd == "send":
            try:
                pubkey = bytes.fromhex(args[1].lower())
            except ValueError:
                print("invalid public key destination")
                continue

            try:
                amount = int(args[2])
            except ValueError:
                print("invalid amount type")
                continue

            with chain_lock:
                transactions = deepcopy(list(CHAIN.transactions.values()))
            wallet.load_transactions(transactions)

            txn = wallet.create_txn(pubkey, amount)

            if txn is None:
                print("failed")
                continue

            wallet.add_pending(txn)
            print("    TXN ID:", txn.txn_id.hex())
            
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
            peers = wallet.find_peers()
            if not peers:
                print("No peers online!")
                continue
            
            print("PUBKEY\t\tNAME\t\tPORT")
            for p in peers:
                print(p.pub_key.hex(), p.name, p.port, sep='\t')
        
        elif cmd == "pending":
            with chain_lock:
                transactions = deepcopy(list(CHAIN.transactions.values()))
            wallet.load_transactions(transactions)

            pending_txns = wallet.get_pending_transactions()
            if not pending_txns:
                print("No pending transactions")
                continue
            for txn in pending_txns:
                print('    ', txn)

        elif cmd == "help":
            print("Commands:\n\tbalance\t\tview balance\n\tpeers\t\tlist peers")

        elif cmd == "quit":
            return

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
                miner.logger.debug('added ' + txn.txn_id.hex() + ' to pool')

        for i, txn in enumerate(pool):
            if used[i]:
                continue

            miner.logger.debug("looking at " + txn.txn_id.hex())

            if not chain.verify_transaction(txn):
                miner.logger.debug("bad txn, removing from pool")
                # discard invalid txn
                pool.pop(i)
                used.pop(i)
                continue

            miner.logger.debug("adding txn to block")
            used[i] = True
            miner.add_pending_txn(txn)
            chain.apply_transaction(txn)

            if miner.num_pending_txns() >= rules.MAX_TXN_COUNT:
                return True


def find_nonce(miner: Miner, chain: BlockChain, pool: list, used: list):
    global CHAIN_MODIFIED, BLOCK_QUEUE, OUT_QUEUE
    miner.logger.debug("started mining")

    chain_head = chain.head_block.data
    block = miner.compose_block(chain_head.block_hash, chain_head.height + 1)

    miner.first_nonce()
    while nonce := miner.next_nonce():
        if miner.valid_nonce(block, nonce):
            block.set_nonce(nonce)

            miner.logger.debug("found nonce: " + str(nonce) + " for block = " + block.block_hash.hex())

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
            miner.logger.debug("chain was modified")
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
            miner.logger.debug('copied chain')
        
        if not accept_txns(miner, chain, pool, used):
            continue

        find_nonce(miner, chain, pool, used)


def handle_message(conn, msg):
    global BLOCK_QUEUE, TXN_QUEUE

    if msg is None:
        return

    msg_type = msg.get('type')
    if msg_type is None:
        return
    
    if msg_type == "block":
        data = msg.get('data')
        if data is None:
            return

        block = Block.from_json(data)
        if block is None:
            return

        with block_queue_lock:
            BLOCK_QUEUE.append(block)

    elif msg_type == "block-list":
        data = msg.get('data')
        if data is None:
            return
        
        blocks = []
        for level in data:
            blocks += [Block.from_json(b_json) for b_json in level]
        
        if not all(blocks):
            return

        with block_queue_lock:
            BLOCK_QUEUE += blocks

    elif msg_type == "transaction":
        data = msg.get('data')
        if data is None:
            return

        txn = Transaction.from_json(data)
        if txn is None:
            return
            
        with txn_queue_lock:
            TXN_QUEUE.append(txn)

    elif msg_type == "block_request":
        # conn.send(CHAIN)
        pass


def run_network_in(network_in: network_util.IncomingNetworkInterface, display_name: str):
    network_in.start_listening()
    
    # send catalog updates in background
    #threading.Thread(target=send_catalog_updates, args=(network_in.pub_key, network_in.port, display_name), daemon=True).start()

    while True:
        (conn, msg) = network_in.accept_message()
        handle_message(conn, msg)
        conn.close()


def run_network_out(network_out: network_util.OutgoingNetworkInterface):
    while True:
        if OUT_QUEUE:
            with out_queue_lock:
                json_data = OUT_QUEUE.pop(0)
            network_out.logger.debug("broadcasting type " + json_data['type'])
            network_out.broadcast(json_data)
        time.sleep(0.2)


def run_maintainer():
    global BLOCK_QUEUE, CHAIN, CHAIN_MODIFIED

    while True:
        if BLOCK_QUEUE:
            with block_queue_lock:
                block = BLOCK_QUEUE.pop(0)
            
            with chain_lock:
                if CHAIN.insert_block(block):
                    print("\nNEW BLOCK PUBLISHED\n")
                    CHAIN.logger.debug("inserting block " + block.block_hash.hex())
                    CHAIN.save_block_to_file(block)
                    with chain_modified_lock:
                        CHAIN_MODIFIED = True
                else:
                    CHAIN.logger.debug("rejecting block " + block.block_hash.hex())


def usage(status):
    print(f"{sys.argv[0]} DISPLAY_NAME")
    sys.exit(status)


def main():
    if len(sys.argv) < 2:
        usage(1)
    
    display_name = sys.argv[1]
    
    pub_key = crypto.load_public_key()
    pri_key = crypto.load_private_key()

    threads = []

    network_out = network_util.OutgoingNetworkInterface(pub_key)
    threads.append(threading.Thread(target=run_network_out, args=(network_out,), daemon=True))

    miner = Miner(pub_key, pri_key)
    threads.append(threading.Thread(target=run_miner, args=(miner,), daemon=True))

    wallet = Wallet(pub_key, pri_key)
    threads.append(threading.Thread(target=run_wallet, args=(wallet,), daemon=True))

    network_in = network_util.IncomingNetworkInterface(pub_key)
    threads.append(threading.Thread(target=run_network_in, args=(network_in,display_name), daemon=True))

    threads.append(threading.Thread(target=run_maintainer, daemon=True))

    global CHAIN
    CHAIN = BlockChain()
    CHAIN.load_chain()
    
    for thread in threads:
        thread.start()
    
    for thread in threads:
        thread.join()

if __name__ == "__main__":
    main()
