def bytes_to_bits(byte_array):
    bits = []
    for byte in byte_array:
        for i in reversed(range(8)):
            bits.append(byte >> i & 1)
    return bits
