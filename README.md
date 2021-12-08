## NDCoin

### 0. Install Packages
```
$ pip3 install -r requirements.txt
```
### 1.  Generate a ECDSA key pair
To set up a node, you must first generate a public/private key pair:
```
$ ./gen-keys.py
```

NOTE (for dthain):  this node already has a public/private key stored in the `.keys` directory.  It is recommended that you start with this key pair, as the genesis block provides coins to this public key.  For additional nodes, you can overwrite this key pair with the `-f` flag.

### 2.  Run a node
Usage: 
```
  ./node.py DISPLAY_NAME [-m NUM_MINERS]
```
Example:   Run a node with display name "Test User", with one miner thread running in the background.
```
$ ./node.py 'Test User'
```

### 3.  Use Wallet

Assuming another node is runnning on `student13.cse.nd.edu`:
```
$ ./node.py 'Test User'
> help
Commands:
        balance                 view relevant transactions and total balance
        peers                   list peers currently in network
        pending                 fetch a list of pending transactions, not yet accepted to the blockchain
        send [pub_key] [amt]    send `amt` coins to identity associated with `pub_key`
        quit                    exit program
> balance
Relevant Transactions:
    06eeaf7484  COINBASE to fba402ee for 50
Balance: 50
> peers
DISPLAY_NAME    NAME                            PORT            PUBKEY
node1           student13.cse.nd.edu            53806           05dcc16ad14b1fab5a417d5f8a99b0531950cabcb79c3ade560fc5f295df1d357cf39b9129992e7a7494a018b2eb01b5a52695385f6072ac6bc5f84afa91f72d
> send 05dcc16ad14b1fab5a417d5f8a99b0531950cabcb79c3ade560fc5f295df1d357cf39b9129992e7a7494a018b2eb01b5a52695385f6072ac6bc5f84afa91f72d 10
    TXN ID: cebde3a8a85843e4a4f2d0f863466fafafcff8f3df4a9865960de78c24cfaf95
> pending
    cebde3a8a8  fba402ee sent 05dcc16ad 10
miner 0 found nonce in 13.65s
NEW BLOCK PUBLISHED
> balance
Relevant Transactions:
    06eeaf7484  COINBASE to fba402ee for 50
    e68eb055ee  COINBASE to fba402ee for 50
    cebde3a8a8  fba402ee sent 05dcc16ad 10
Balance: 90
> quit
```

### 4. Experiment with more miners
```
$ ./node.py 'Test User' -m 20
> send abc123 10
	TXN ID: ee308730cfeb88a09cb92bd841a03842b533d0f4ca3633a76f6f7410e5b09727
>
miner 10 found nonce in 73.89s
NEW BLOCK PUBLISHED
>
```