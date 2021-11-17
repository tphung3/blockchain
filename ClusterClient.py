import time
import hashlib
from HashTableClient import HashTableClient, MessageTransmissionException


def _hash(string, n):
    # hash string into an int in range [0, n)
    h = hashlib.md5(string.encode())
    return int(h.hexdigest(), 16) % n


class ClusterClient:
    def __init__(self, N, K):
        self.N = N
        self.K = K
        self.clients = []

    def connect(self, name):
        names = [f"{name}-{n}" for n in range(self.N)]

        for name in names:
            client = HashTableClient()

            while not client.connect(name):
                time.sleep(5)
            
            self.clients.append(client)

    def replicas(self, key):
        if not isinstance(key, str):
            raise TypeError("Invalid parameters: 'key' must be a string")

        i = _hash(key, self.N)
        return [self.clients[(i+j) % self.N] for j in range(self.K)]

    def cleanup(self):
        # disconnect all clients
        for client in self.clients:
            client.cleanup()

    def insert(self, key, value):
        for client in self.replicas(key):
            while True: 
                try:
                    client.insert(key, value)
                    break
                except MessageTransmissionException:
                    # client is unavailable, wait 5s and try again
                    client.restart_connection()
                    time.sleep(5)
                    continue

    def remove(self, key):
        value = None

        for client in self.replicas(key):
            while True: 
                try:
                    v = client.remove(key)
                    # sanity check
                    if not (value is None or v == value):
                        print("v:", v)
                        print("value:", value)
                        print("client:", client.name)
                        print("key:", key)
                        print("hash:", _hash(key, self.N))
                    value = v
                    break
                except MessageTransmissionException:
                    # client is unavailable, wait 5s and try again
                    client.restart_connection()
                    time.sleep(5)
                    continue

        return value


    def lookup(self, key):
        while True:
            for client in self.replicas(key):
                try:
                    return client.lookup(key)
                except MessageTransmissionException:
                    continue

            # none of the replicas were available, so wait 5 seconds and try again
            for client in self.replicas(key):
                client.restart_connection()

            time.sleep(5)

    def scan(self, regex):
        # key -> (value, hashes' dist from original replica)
        matches_dict = dict()

        for client in self.clients:
            matches = [] 

            while True:
                try:
                    matches = client.scan(regex)
                    break
                except MessageTransmissionException:
                    client.restart_connection()
                    time.sleep(5)
                    continue

            for i, (key, value) in enumerate(matches):
                d = self._dist_from_original(key, i)

                if key in matches_dict:
                    # when collision, take closest replica to original
                    if d < matches_dict[key][1]:
                        matches_dict[key] = (value, d)
                else:
                    matches_dict[key] = (value, d)

        return [
            [key, matches_dict[key][0]] for key in matches_dict
        ]

    def _dist_from_original(self, string, i):
        o = _hash(string, self.N)

        if i < o:
            # wrapped around
            return self.N - i + o + 1

        return o - i

