import logging
import os


LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'node.log')


def bytes_to_bits(byte_array):
    bits = []
    for byte in byte_array:
        for i in reversed(range(8)):
            bits.append(byte >> i & 1)
    return bits


def get_logger():
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(format='%(asctime)s,%(msecs)d %(levelname)s [%(filename)s:%(funcName)s] %(message)s',
        datefmt='%Y-%m-%d:%H:%M:%S',
        level=logging.DEBUG,
        filename=LOG_FILE)
    logger = logging.getLogger(__name__)
    return logger
