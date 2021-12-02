#!/usr/bin/env python3

import sys
import time
import threading
from copy import deepcopy
import rules
import crypto
import network_util
from chain import BlockChain
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

CHAIN = BlockChain()        # modified by main – used by all
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

    while line := input("> "):
        args = line.split()
        
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
            peers = wallet.find_peers()
            if not peers:
                print("No peers online!")
                continue
            
            print("PUBKEY\t\tADDR\t\tPORT")
            for p in peers:
                print(p.pub_key.hex()[:8], p.address, p.port, sep='\t')
        
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
    threading.Thread(target=send_catalog_updates, args=(network_in.pub_key, network_in.port, display_name), daemon=True).start()

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


def usage(status):
    print(f"{sys.argv[0]} DISPLAY_NAME")
    sys.exit(status)


def main():
    if len(sys.argv) < 2:
        usage(1)
    
    display_name = sys.argv[1]
    
    pub_key = crypto.load_public_key()
    pri_key = crypto.load_private_key()

    network_out = network_util.OutgoingNetworkInterface()
    threading.Thread(target=run_network_out, args=(network_out,), daemon=True).start()
    
    miner = Miner(pub_key, pri_key)
    from transaction import Transaction
    txn_list = [{"txn_id": "1f7fde67c75b03ceea8d745aeb82c0ce127f667992cc710f970dc3a90abd63d4", "inputs": [{"txn_id": "06eeaf748440eccc5fe44bc53b3c032b183b57f4274361484e4fbea508ebc872", "index": 0}], "outputs": [{"pub_key": "61626364", "amount": 40, "signature": "5061e1f8c8fe507381dfee844b5def68c8c570f290807032ff13b844cf4eeb15a111fa4b41b08f31e1d9bcc951f023d7aeb23d00917d6eb1f0e14a4f8b57a640"}, {"pub_key": "fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166", "amount": 10, "signature": "83e237ce72a5f68c9fb87bace4aef2a025e6e6651d4f346925b71148a5c1ff725b7cc2e21b5e68f43b22da24e58aace447ee471b09d7eb0a692c88d5103543bc"}]},{"txn_id": "ae1d53dc68663e84e56cdb77c2ea0c15eddaa177427e2662fc070306801005bd", "inputs": [{"txn_id": "1f7fde67c75b03ceea8d745aeb82c0ce127f667992cc710f970dc3a90abd63d4", "index": 1}], "outputs": [{"pub_key": "61626364", "amount": 5, "signature": "98a2b03835c6a0068f4bb04710314f49b8cdb45866969a35e389ff38206d17ce6fb1808c0b3080b231430e11a94b9b6db5c24bef4a68433a9bd1edbbfc2ec2de"}, {"pub_key": "fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166", "amount": 5, "signature": "71c4d43a9d9c82b1d848119da1c2d1fe80fd62590635398d05e4060239a40a36906661136f0277bfd0efc10c8cf619cbeea22fcee922af744f776869afc75cf0"}]},{"txn_id": "335f9b62e474e4cb44876f249e380edad06f7a353c1323acf8fb9488f72ff8f6", "inputs": [{"txn_id": "ae1d53dc68663e84e56cdb77c2ea0c15eddaa177427e2662fc070306801005bd", "index": 1}], "outputs": [{"pub_key": "61626364", "amount": 4, "signature": "5f5155d1a28fd1d586b336b248dd83e224535e22b5ab534e3668b7d023cef9011d1c1f7ca7ed8c845c51493452e782420f08ea4d064ae7f0354f4dae2deb06ce"}, {"pub_key": "fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166", "amount": 1, "signature": "3a45b96c71c1eed88f84c1abe732c77138403b582c7e8a70549e6f17ba05419d4725a83c7f93afc1d45a0b727d25b820e4e85e40ca1051c9ca17003efccf5d1c"}]}]
    txns = [Transaction.from_json(txn_json) for txn_json in txn_list]
    global TXN_QUEUE
    TXN_QUEUE = txns
    threading.Thread(target=run_miner, args=(miner,), daemon=True).start()

    block = Block.from_json({'hash': '0000029fe2de502979b5b1e345ff58b4c47f9f872c26999bc47752930a8a5f76', 'prev_hash': '00000e9f2fb735130801b4c31e40c3b9c6fa0789a13f8c5d685cd1602c97bafb', 'height': 1, 'nonce': 66240216508772406228315848838552293799641861242416215840665602550228984815026, 'transactions': [{'txn_id': 'adbcd37eb20dfe3cfe174358ac32c6b2da4027ea48ffd47e9af73689f4dc015f', 'inputs': [], 'outputs': [{'pub_key': 'fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166', 'amount': 50, 'signature': '108f9bdcb45f3823b78a76344fcb1c9cbfe3dbdb1fbc6869c52fd0c84ffae25f116d7253034e753171da1b0dab186cc1c0af656969379451308172a1311e5ed8'}]}, {'txn_id': '1f7fde67c75b03ceea8d745aeb82c0ce127f667992cc710f970dc3a90abd63d4', 'inputs': [{'txn_id': '06eeaf748440eccc5fe44bc53b3c032b183b57f4274361484e4fbea508ebc872', 'index': 0}], 'outputs': [{'pub_key': '61626364', 'amount': 40, 'signature': '5061e1f8c8fe507381dfee844b5def68c8c570f290807032ff13b844cf4eeb15a111fa4b41b08f31e1d9bcc951f023d7aeb23d00917d6eb1f0e14a4f8b57a640'}, {'pub_key': 'fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166', 'amount': 10, 'signature': '83e237ce72a5f68c9fb87bace4aef2a025e6e6651d4f346925b71148a5c1ff725b7cc2e21b5e68f43b22da24e58aace447ee471b09d7eb0a692c88d5103543bc'}]}, {'txn_id': 'ae1d53dc68663e84e56cdb77c2ea0c15eddaa177427e2662fc070306801005bd', 'inputs': [{'txn_id': '1f7fde67c75b03ceea8d745aeb82c0ce127f667992cc710f970dc3a90abd63d4', 'index': 1}], 'outputs': [{'pub_key': '61626364', 'amount': 5, 'signature': '98a2b03835c6a0068f4bb04710314f49b8cdb45866969a35e389ff38206d17ce6fb1808c0b3080b231430e11a94b9b6db5c24bef4a68433a9bd1edbbfc2ec2de'}, {'pub_key': 'fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166', 'amount': 5, 'signature': '71c4d43a9d9c82b1d848119da1c2d1fe80fd62590635398d05e4060239a40a36906661136f0277bfd0efc10c8cf619cbeea22fcee922af744f776869afc75cf0'}]}, {'txn_id': '335f9b62e474e4cb44876f249e380edad06f7a353c1323acf8fb9488f72ff8f6', 'inputs': [{'txn_id': 'ae1d53dc68663e84e56cdb77c2ea0c15eddaa177427e2662fc070306801005bd', 'index': 1}], 'outputs': [{'pub_key': '61626364', 'amount': 4, 'signature': '5f5155d1a28fd1d586b336b248dd83e224535e22b5ab534e3668b7d023cef9011d1c1f7ca7ed8c845c51493452e782420f08ea4d064ae7f0354f4dae2deb06ce'}, {'pub_key': 'fba402ee09ca9b71faffd70212a6a25aa57b9d72353a7f0e62a70e61ff325b68ac63039d5bf654cddcf2595961d0b0d342a13b2b31f103198bdf320259dc6166', 'amount': 1, 'signature': '3a45b96c71c1eed88f84c1abe732c77138403b582c7e8a70549e6f17ba05419d4725a83c7f93afc1d45a0b727d25b820e4e85e40ca1051c9ca17003efccf5d1c'}]}]})
    CHAIN.insert_block(block)
    wallet = Wallet(pub_key, pri_key)
    threading.Thread(target=run_wallet, args=(wallet,), daemon=True).start()

    network_in = network_util.IncomingNetworkInterface(pub_key)
    run_network_in(network_in, display_name)


if __name__ == "__main__":
    main()
