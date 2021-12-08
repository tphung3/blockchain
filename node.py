#!/usr/bin/env python3

import sys
import time
import threading, queue
from copy import deepcopy
import rules
import crypto
import network_util
from chain import BlockChain
from block import Block
from transaction import Transaction
from wallet import Wallet
from miner import Miner


BLOCK_QUEUE = queue.Queue()    # from network and miner – used by main and miner
REQUEST_QUEUE = queue.Queue()  # from network – used by main
OUT_QUEUE = queue.Queue()      # from main, wallet, and miner – used by network
TXN_QUEUES = []                # from network and wallet – used by miner (list of queue.Queue objects)

CHAIN = None                # modified by main – used by all
chain_lock = threading.Lock()

CHAIN_MODS = []   # has chain been modified while mining? - list of threading.Event objects for each miner


def send_catalog_updates(pub_key, port, display_name):
    # send update every minute
    while True:
        start = time.time()
        network_util.send_catalog_update(pub_key, port, display_name)
        time.sleep(60 - (time.time() - start))


def run_wallet(wallet: Wallet):
    global TXN_QUEUES, OUT_QUEUE, CHAIN

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
            
            for txn_queue in TXN_QUEUES:
                txn_queue.put(txn)

            OUT_QUEUE.put(txn.to_message())
        
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
            
            print("DISPLAY_NAME\t\tPUBKEY\t\tNAME\t\tPORT")
            for p in peers:
                print(p.display_name, p.pub_key.hex(), p.name, p.port, sep='\t')
        
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


def accept_txns(miner: Miner, chain: BlockChain, txn_queue: queue.Queue, chain_mod_event: threading.Event, pool: list, used: list):
    miner.reset_pending_txns()
    s = time.time()

    while True:
        # accept incoming txns until timeout, max txn count, or chain modification
        if chain_mod_event.is_set():
            chain_mod_event.set()
            return False

        # timeout
        if (time.time() - s) >= rules.MINER_WAIT_TIMEOUT:
            # more than just coinbase txn
            if miner.num_pending_txns() > 1:
                return True

            # keep waiting, but refresh timeout
            s = time.time()

            while not txn_queue.empty():
                txn = txn_queue.get()
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


def find_nonce(miner: Miner, chain: BlockChain, chain_mod_event: threading.Event, pool: list, used: list):
    global BLOCK_QUEUE, OUT_QUEUE
    miner.logger.debug("started mining")

    chain_head = chain.head_block.data
    block = miner.compose_block(chain_head.block_hash, chain_head.height + 1)

    miner.first_nonce()
    while nonce := miner.next_nonce():
        if miner.valid_nonce(block, nonce):
            block.set_nonce(nonce)

            miner.logger.debug("found nonce: " + str(nonce) + " for block = " + block.block_hash.hex())

            BLOCK_QUEUE.put(block)
            OUT_QUEUE.put(block.to_message())

            # stop other miners within machine
            chain_mod_event.set()

            # remove txns used in block
            pool = [txn for i, txn in enumerate(pool) if not used[i]]
            used = [False for _ in pool]

            return True

        # invalid nonce + chain has been modified
        elif chain_mod_event.is_set():
            miner.logger.debug("chain was modified")
            for i in range(len(used)):
                # unmark all txns in pool
                used[i] = False

            chain_mod_event.clear()

            return False


def run_miner(miner: Miner, txn_queue: queue.Queue, chain_mod_event: threading.Event, miner_num: int):
    global CHAIN

    pool = []   # pool of txns to mine
    used = []   # flag for each txn (if in current mining block)

    while True:
        with chain_lock:
            # checkout current state of chain
            chain = deepcopy(CHAIN)
            miner.logger.debug('copied chain')
        
        if not accept_txns(miner, chain, txn_queue, chain_mod_event, pool, used):
            continue

        s = time.time()
        if find_nonce(miner, chain, chain_mod_event, pool, used):
            print(f"miner {miner_num} found nonce in {time.time() - s:.2f}s")


def handle_message(conn, msg):
    global BLOCK_QUEUE, TXN_QUEUES

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

        BLOCK_QUEUE.put(block)

    elif msg_type == "block-list":
        data = msg.get('data')
        if data is None:
            return
        
        blocks = []
        for level in data:
            blocks += [Block.from_json(b_json) for b_json in level]
        
        if not all(blocks):
            return

        for block in blocks:
            BLOCK_QUEUE.put(blocks)

    elif msg_type == "transaction":
        data = msg.get('data')
        if data is None:
            return

        txn = Transaction.from_json(data)
        if txn is None:
            return

        for txn_queue in TXN_QUEUES:
            txn_queue.put(txn)

    elif msg_type == "block_request":
        # conn.send(CHAIN)
        pass


def run_network_in(network_in: network_util.IncomingNetworkInterface, display_name: str):
    network_in.start_listening()
    
    # send catalog updates in background
    threading.Thread(target=send_catalog_updates, args=(network_in.pub_key, network_in.port, display_name), daemon=True).start()

    while True:
        (conn, msg) = network_in.accept_message()
        handle_message(conn, msg)
        conn.close()


def run_network_out(network_out: network_util.OutgoingNetworkInterface):
    while True:
        if not OUT_QUEUE.empty():
            json_data = OUT_QUEUE.get()
            network_out.logger.debug("broadcasting type " + json_data['type'])
            network_out.broadcast(json_data)
        time.sleep(0.2)


def run_maintainer():
    global BLOCK_QUEUE, CHAIN, CHAIN_MODS

    while True:
        if not BLOCK_QUEUE.empty():
            block = BLOCK_QUEUE.get()
            
            with chain_lock:
                if CHAIN.insert_block(block):
                    print("NEW BLOCK PUBLISHED\n> ", end="")
                    CHAIN.logger.debug("inserting block " + block.block_hash.hex())
                    CHAIN.save_block_to_file(block)
                    for event in CHAIN_MODS:
                        event.set()
                else:
                    CHAIN.logger.debug("rejecting block " + block.block_hash.hex())
        time.sleep(0.2)


def usage(status):
    print(f"{sys.argv[0]} DISPLAY_NAME [-m MINERS]")
    sys.exit(status)


def main():
    if len(sys.argv) < 2:
        usage(1)
    
    display_name = sys.argv[1]

    num_miners = 1
    if len(sys.argv) == 4 and sys.argv[2] == '-m':
        try:
            num_miners = int(sys.argv[3])
        except ValueError:
            print("Invalid number of miners", sys.stderr)
            sys.exit(1)
    
    pub_key = crypto.load_public_key()
    pri_key = crypto.load_private_key()

    threads = []

    network_out = network_util.OutgoingNetworkInterface(pub_key)
    threads.append(threading.Thread(target=run_network_out, args=(network_out,), daemon=True))

    network_in = network_util.IncomingNetworkInterface(pub_key)
    threads.append(threading.Thread(target=run_network_in, args=(network_in,display_name), daemon=True))

    threads.append(threading.Thread(target=run_maintainer, daemon=True))

    for i in range(num_miners):
        txn_queue = queue.Queue()
        TXN_QUEUES.append(txn_queue)
        chain_mod_event = threading.Event()
        CHAIN_MODS.append(chain_mod_event)
        miner = Miner(pub_key, pri_key)
        threads.append(threading.Thread(target=run_miner, args=(miner,txn_queue,chain_mod_event,i), daemon=True))

    global CHAIN
    CHAIN = BlockChain()
    CHAIN.load_chain()
    
    for thread in threads:
        thread.start()
    
    # wallet is main thread
    wallet = Wallet(pub_key, pri_key)
    run_wallet(wallet)

if __name__ == "__main__":
    main()
