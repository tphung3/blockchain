import json
import struct
import socket
import http.client
from dataclasses import dataclass
from typing import List
from utils import get_logger


BUFSIZ = 1024
CATALOG_SERVER = ('catalog.cse.nd.edu', 9097)
NETID = "jrundle"
PROJECT = "nd-coin"
TYPE = "crypto"


@dataclass
class Peer:
    pub_key: bytes
    address: str
    port: int
    display_name: str
    lastheardfrom: float


def find_peers(my_pub_key) -> List[Peer]:
    conn = http.client.HTTPConnection(*CATALOG_SERVER)
    conn.request("GET", "/query.json")
    data = conn.getresponse().read()

    entries = [d for d in json.loads(data) if d.get('type') == TYPE and d.get('project') == PROJECT]
    peers = dict()

    attrs = ('address', 'port', 'pub_key', 'display_name', 'lastheardfrom')
    for entry in entries:
        if not all(map(lambda attr: entry.get(attr), attrs)):
            continue

        try:
            peer = Peer(
                bytes.fromhex(entry['pub_key']),
                entry['address'],
                int(entry['port']),
                entry['display_name'],
                float(entry['lastheardfrom'])
            )
        except (ValueError, KeyError):
            continue
        
        if peer.pub_key == my_pub_key:
            continue

        pub_key = entry['pub_key']
        
        if pub_key in peers:
            if entry['lastheardfrom'] > peers[pub_key].lastheardfrom:
                peers[pub_key] = peer
        else:
            peers[pub_key] = peer

    conn.close()
    
    return list(peers.values())


def send_catalog_update(pubkey: bytes, port: int, display_name: str, type_: str=TYPE, project: str=PROJECT, netid: str=NETID):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    data = json.dumps({
        "type": type_,
        "owner": netid,
        "port": port,
        "project": project,
        "pub_key": pubkey.hex(),
        "display_name": display_name
    }).encode()
    s.sendto(data, CATALOG_SERVER)
    s.close()


def send_json(s, json_obj):
    json_str = json.dumps(json_obj)
    size = len(json_str)

    size_bytes = struct.pack("!i", size)
    json_bytes = json_str.encode()

    msg = size_bytes + json_bytes

    try:
        return s.sendall(msg) is None
    except OSError:
        return False


def receive(s, n):
    try:
        return s.recv(n)
    except OSError:
        return 0 


def rec_json(s):
    # Raises ValueError if invalid JSON
    size = rec_int(s)

    if size is None:
        return None
    
    # should also have json ready, so timeout if not
    s.settimeout(0.1)
    json_str = rec_string(s, size)
    s.settimeout(None)

    if json_str is None:
        return None

    try:
        return json.loads(json_str)
    except json.decoder.JSONDecodeError:
        raise ValueError


def rec_string(s, size):
    read = 0
    message = ""
    
    while read < size:
        bufsiz = min(size - read, BUFSIZ)
        content = receive(s, bufsiz)
    
        if not content:
            return None

        message += content.decode(errors='replace')
        read += len(content)
    
    return message


def rec_int(s):
    val = receive(s, 4)
    
    if not val or len(val) != 4:
        return None 

    # recover endianness from network standard
    return struct.unpack("!i", val)[0]


class IncomingNetworkInterface:
    def __init__(self, pub_key):
        self.pub_key = pub_key
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.port = 0

        self.logger = get_logger()
    
    def start_listening(self):
        self.socket.bind(('', 0))
        _, self.port = self.socket.getsockname()

        self.socket.listen(8)
        self.logger.debug("Listening on port " + str(self.port))
    
    def accept_message(self):
        conn = self.socket.accept()
        message = rec_json(conn)
        return (conn, message)


class OutgoingNetworkInterface:
    def __init__(self, pub_key):
        self.pub_key = pub_key
        self.connections = dict()
        self.logger = get_logger()

    def broadcast(self, json_data):
        self.update_connections()

        for (peer, conn) in self.connections.values():
            send_json(conn, json_data)
    
    def update_connections(self):
        for peer in find_peers(self.pub_key):
            if peer.pub_key in self.connections:
                # are details the same
                (cached_peer, conn) = self.connections[peer.pub_key]
                if peer.address == cached_peer.address and cached_peer.port == peer.port:
                    continue

            try:
                conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                conn.connect((peer.address, peer.port))
                self.connections[peer.pub_key] = (peer, conn)
            except (TimeoutError, InterruptedError, ConnectionRefusedError):
                continue


if __name__ == "__main__":
    peers = find_peers(None)
    print("PUBKEY\t\tADDR\t\tPORT")
    for p in peers:
        print(p.pub_key.hex()[:8], p.address, p.port, sep='\t')
