from utils import bytes_to_bits

# Mining rules
MINING_REWARD = 50
MIN_ZEROS = 20
MINER_WAIT_TIMEOUT = 5
MAX_TXN_COUNT = 20

def valid_block_hash(h):
    bits = bytes_to_bits(h)
    return all(map(lambda b: b == 0, bits[:MIN_ZEROS]))


# chain rules
MAX_BLOCKS_BEHIND = 10
