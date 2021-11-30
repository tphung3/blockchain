#!/usr/bin/env python3

import ecdsa
import hashlib
import os
import sys


CURVE = ecdsa.SECP256k1
HASH_FUNC = hashlib.sha256

KEY_DIR = os.path.join(os.path.dirname(__file__), ".keys")
PRIKEY_FILE = os.path.join(KEY_DIR, "ecdsa_key")
PUBKEY_FILE = os.path.join(KEY_DIR, "ecdsa_key.pub")


def double_sha256(data: bytes) -> bytes:
    h1 = hashlib.sha256(data)
    h2 = hashlib.sha256(h1.digest())
    return h2.digest()


def generate_private_key() -> ecdsa.SigningKey:
    return ecdsa.SigningKey.generate(curve=CURVE, hashfunc=HASH_FUNC)


def get_public_key(private_key: ecdsa.SigningKey) -> ecdsa.VerifyingKey:
    return private_key.get_verifying_key()


def save_key(key, key_file, overwrite):
    if os.path.exists(key_file) and not overwrite:
        raise ValueError("Key already exists at that location")
    
    os.makedirs(KEY_DIR, exist_ok=True)

    with open(key_file, 'wb') as stream:
        pem = key.to_pem()
        stream.write(pem)


def save_private_key(private_key: ecdsa.SigningKey, key_file=PRIKEY_FILE, overwrite=False):
    save_key(private_key, key_file, overwrite)


def save_public_key(public_key: ecdsa.VerifyingKey, key_file=PUBKEY_FILE, overwrite=False):
    save_key(public_key, key_file, overwrite)


def load_private_key(key_file=PRIKEY_FILE):
    with open(key_file, 'rb') as stream:
        pem = stream.read()
        sk = ecdsa.SigningKey.from_pem(pem, hashfunc=HASH_FUNC)
        return key_to_bytes(sk)


def load_public_key(key_file=PUBKEY_FILE):
    with open(key_file, 'rb') as stream:
        pem = stream.read()
        vk = ecdsa.VerifyingKey.from_pem(pem, hashfunc=HASH_FUNC)
        return key_to_bytes(vk)


def sign(private_key, data: bytes) -> bytes:
    private_key_obj = bytes_to_private_key(private_key)
    return private_key_obj.sign(data)


def verify(public_key: bytes, signature: bytes, data: bytes) -> bool:
    try:
        public_key_obj = bytes_to_public_key(public_key)
        return public_key_obj.verify(signature, data)
    except Exception as e:
        print("error during verify:", e, file=sys.stderr)
        return False


def bytes_to_private_key(private_key_bytes: bytes):
    return ecdsa.SigningKey.from_string(private_key_bytes, curve=CURVE, hashfunc=HASH_FUNC) 


def bytes_to_public_key(public_key_bytes: bytes):
    return ecdsa.VerifyingKey.from_string(public_key_bytes, curve=CURVE, hashfunc=HASH_FUNC) 


def key_to_bytes(key):
    return key.to_string()


def key_to_string(key):
    return key_to_bytes(key).hex()


if __name__ == "__main__":
    load = False

    if load:
        private_key = load_private_key()
        public_key  = load_public_key()
    else:
        private_key = generate_private_key()
        public_key  = get_public_key(private_key)

        save_private_key(private_key)
        save_public_key(public_key)

    print("ECDA key pair")
    print("Private Key:", key_to_string(private_key))
    print("Public Key: ", key_to_string(public_key))

    while data := input("Data to Sign: ").encode():
        signature = sign(data, private_key)
        print(signature.hex())

        assert verify(signature, data, public_key) is True
        print("Verified")
