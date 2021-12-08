#!/usr/bin/env python3

import sys
import crypto


def main():
    overwrite = False
    
    if len(sys.argv) > 1:
        if sys.argv[1].lower() == '-f':
            overwrite = True
        else:
            print(f"Usage: {sys.argv[0]} [-f]", file=sys.stderr)
            sys.exit(1)

    private_key = crypto.generate_private_key()
    public_key = crypto.get_public_key(private_key)

    try:
        crypto.save_private_key(private_key, key_file=crypto.PRIKEY_FILE, overwrite=overwrite)
        print("Saved private key to", crypto.PRIKEY_FILE)
    except ValueError:
        print(f"Private key already exists at {crypto.PRIKEY_FILE}.  Turn on -f flag to overwrite.", file=sys.stderr)
        sys.exit(1)
    
    try:
        crypto.save_public_key(public_key, key_file=crypto.PUBKEY_FILE, overwrite=overwrite)
        print("Saved public key to", crypto.PUBKEY_FILE)
    except ValueError as e:
        print(f"Public key already exists at {crypto.PUBKEY_FILE}.  Turn on -f flag to overwrite.", file=sys.stderr)
        sys.exit(1)

    print("Public Key:", crypto.key_to_string(public_key))
    print("Private Key:", crypto.key_to_string(private_key))


if __name__ == "__main__":
    main()
