#import relevant libraries
import os

#get desired number of nodes
num_nodes = int(input('> '))

#clone as many nodes
for i in range(num_nodes):
    os.system(f'git clone https://github.com/tphung3/blockchain.git node{i}')
    os.system(f'cd node{i}; git checkout xput');

#generate pairs of keys for all nodes EXCEPT FIRST NODE as first node needs to claim the mining of the genesis block
for i in range(1, num_nodes):
    os.system(f'cd node{i};./gen-keys.py -F')
