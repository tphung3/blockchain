## NDCoin
NDCoin is a secure and reliable peer-to-peer payment sevice.

### 0. Setup
First, we strongly suggest that NDCoin nodes are run on the Notre Dame's student machines.

Second, create an empty directory for the creation of nodes in system. Then make sure that you have python 3 installed and in your PATH as `python`. Then run `python prep.py` to spawn different nodes as each node requires a separate directory. `prep.py` will ask you to input the number of nodes you'd like to spawn, and we recommend a low number, maybe 3, at first. The python script will clone a NDCoin node to each directory named "node{i}" and generate a new public/private key pair for each additional node spawned. 
Second, we use the `ecdsa` library for any operations related to the key pair, so if you have `pip3` in your PATH, run
```
$ pip3 install -r requirements.txt
```
to install the library.
Otherwise, install `pip3` and run the above command.

### 1.  Generate a ECDSA key pair (Optional)
This section is optional if you run the preparation script `prep.py`. To set up a node, you must first generate a public/private key pair:
```
$ ./gen-keys.py
```

NOTE: do not change the public/private key pair of the first node. This node already has a public/private key stored in the `.keys` directory.  It is recommended that you start with this key pair, as the genesis block provides coins to this public key.  For additional nodes, you can overwrite their key pair with the `-f` flag.

### 2.  Run a node
For each node in the system, open up a terminal and change your working directory to respective nodes. Running a node is as follows.
Usage: 
```
  ./node.py DISPLAY_NAME [-m NUM_MINERS]
```
Example:   Run a node with display name "Test User", with three miner threads running in the background.
```
$ ./node.py 'Test User' -m 3
```

### 3.  Use Wallet
Since the user only interacts with the wallet, below is an example of such interaction. Assuming another node is runnning on `student13.cse.nd.edu`:
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

### 4. Overview of a Node's Structure
Below we'll list and give a brief description of important files and directories in NDCoin's repository:
    * `block.py`: Implements the block object
    * `chain`: Persistent storage of the blockchain
    * `crypto.py`: Helper functions dealing with public/private key pairs
    * `gen-keys.py`: Helper script that generates a pair of keys
    * `miner.py`: Implements the miner object
    * `network_util.py`: Implements the network interface
    * `node.py`: Implements the node's master process when run
    * `prep.py`: Helper script that generates different nodes
    * `rules.py`: Specifies all rules concerning the blockchain, such as mining reward, minimum number of zeros, etc.
    * `transaction.py`: Implements the transaction object
    * `wallet.py`: Implements the wallet object

### 5. Miscellaneous
NDCoin is a collaboration effort from Jack Rundle and Thanh Son Phung for the final project in the Distributed Systems course - Fall 2021 at the University of Notre Dame. We store the source code at `https://github.com/tphung3/blockchain`.

