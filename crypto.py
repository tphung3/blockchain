#!/usr/bin/env python3

import ecdsa
import hashlib


CURVE = ecdsa.SECP256k1
HASH_FUNC = hashlib.sha256


def hash_data(data: bytes) -> bytes:
    h1 = HASH_FUNC(data)
    h2 = HASH_FUNC(h1.digest())
    return h2.digest()


def generate_private_key() -> ecdsa.SigningKey:
    return ecdsa.SigningKey.generate(curve=CURVE, hashfunc=HASH_FUNC)


def get_public_key(private_key: ecdsa.SigningKey) -> ecdsa.VerifyingKey:
    return private_key.get_verifying_key()


def sign(data: bytes, private_key: ecdsa.SigningKey) -> bytes:
    return private_key.sign(data)


def verify(signature: bytes, data: bytes, public_key_bytes: bytes) -> bool:
    public_key = bytes_to_public_key(public_key_bytes)
    return verify_with_object(signature, data, public_key)


def verify_with_object(signature: bytes, data: bytes, public_key: ecdsa.VerifyingKey) -> bool:
    return public_key.verify(signature, data)


def bytes_to_public_key(public_key_bytes: bytes):
    return ecdsa.VerifyingKey.from_string(public_key_bytes, curve=CURVE, hashfunc=HASH_FUNC) 


def key_to_bytes(key):
    return key.to_string()


def key_to_string(key):
    return key_to_bytes(key).hex()


if __name__ == "__main__":
    while data := input("Data to Hash: ").encode():
        h = hash_data(data)
        print(h.hex())

    print("---------\n")

    private_key = generate_private_key()
    public_key  = get_public_key(private_key)

    print("Generating ECDA key pair")
    print("Private Key:", key_to_string(private_key))
    print("Public Key: ", key_to_string(public_key))

    while data := input("Data to Sign: ").encode():
        signature = sign(data, private_key)
        print(signature.hex())

        assert verify_with_object(signature, data, public_key) is True
        assert verify(signature, data, key_to_bytes(public_key)) is True
        print("Verified")


