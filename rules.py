from utils import bytes_to_bits


MINING_REWARD = 50
MIN_ZEROS = 15


def valid_block_hash(h):
    bits = bytes_to_bits(h)
    return all(map(lambda b: b == 0, bits[:MIN_ZEROS]))